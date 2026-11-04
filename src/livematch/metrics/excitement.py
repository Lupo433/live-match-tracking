"""Excitement index: one value (0-100) per second of match, computed incrementally.

Components (each in [0, 1]) of second k, see docs/excitement_index.md:

* ``proximity``  ball close to a goal: mean of max(0, 1 - d / 35 m) over the frames
  with the ball tracked (d = distance to the nearer goal centre);
* ``tempo``      game speed: mean of min(1, ball speed / 15 m/s) and
  min(1, mean outfield speed / 4 m/s);
* ``threat``     recent chances: sum over past shots of 1.5 * xG * exp(-dt / 8 s)
  plus 1.0 * exp(-dt / 25 s) for goals, capped at 1;
* ``turnovers``  possession changes in the last 10 s / 3, capped at 1;
* ``territory``  final-third dominance from pitch control: max over the two teams
  of the control share of the opponent's final third, rescaled (v - 0.25) / 0.5.

raw = 0.25 proximity + 0.15 tempo + 0.35 threat + 0.10 turnovers + 0.15 territory,
smoothed with an exponential moving average (alpha 0.35 per second), then
index = round(100 * min(1, smoothed / 0.75)).
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np

from livematch.schema import PITCH_LENGTH, PITCH_WIDTH

WEIGHTS = {"proximity": 0.25, "tempo": 0.15, "threat": 0.35, "turnovers": 0.10, "territory": 0.15}
PROX_RANGE = 35.0
BALL_SPEED_REF = 15.0
PLAYER_SPEED_REF = 4.0
SHOT_TAU, GOAL_TAU = 8.0, 25.0
SHOT_GAIN, GOAL_GAIN = 1.5, 1.0
TURNOVER_WINDOW, TURNOVER_REF = 10.0, 3.0
EMA_ALPHA = 0.35
SATURATION = 0.75


def index_from_raw(smoothed: float) -> int:
    return int(round(100 * min(1.0, max(0.0, smoothed) / SATURATION)))


class ExcitementTracker:
    """Per-second excitement, updated frame by frame (cheap: a few float ops per frame)."""

    def __init__(self, fps: float) -> None:
        self.fps = fps
        self.frames_per_bucket = max(1, int(round(fps)))
        self.series: list[int] = []
        self.last_components: dict[str, float] = {}
        self._reset_bucket()
        self._smoothed = 0.0
        self._shots: list[tuple[float, float, bool]] = []  # (t, xg, goal)
        self._changes: deque[float] = deque()
        self._last_team: int | None = None
        self._t = 0.0

    def _reset_bucket(self) -> None:
        self._n = 0
        self._prox_sum = 0.0
        self._prox_n = 0
        self._ball_v_sum = 0.0
        self._ball_v_n = 0
        self._pl_v_sum = 0.0
        self._territory: float | None = None

    # ------------------------------------------------------------------ inputs
    def add_shot(self, t: float, xg: float, goal: bool) -> None:
        self._shots.append((t, xg, goal))

    def set_territory(self, home_control_grid: np.ndarray, nx: int, ny: int) -> None:
        """Final-third dominance from a pitch-control grid (row-major from y = 0)."""
        g = home_control_grid.reshape(ny, nx)
        xs = (np.arange(nx) + 0.5) * PITCH_LENGTH / nx
        home_att = float(g[:, xs > PITCH_LENGTH * 2 / 3].mean())
        away_att = float(1.0 - g[:, xs < PITCH_LENGTH / 3].mean())
        self._territory = min(1.0, max(0.0, (max(home_att, away_att) - 0.25) / 0.5))

    def update(
        self,
        t: float,
        ball: np.ndarray,
        ball_speed: float,
        mean_player_speed: float,
        possession_team: int | None,
    ) -> int | None:
        """Consume one frame; returns the index when a one-second bucket closes."""
        self._t = t
        if possession_team is not None and possession_team != self._last_team:
            if self._last_team is not None:
                self._changes.append(t)
            self._last_team = possession_team
        if not (math.isnan(ball[0]) or math.isnan(ball[1])):
            gx = PITCH_LENGTH if ball[0] > PITCH_LENGTH / 2 else 0.0
            d = math.hypot(ball[0] - gx, ball[1] - PITCH_WIDTH / 2)
            self._prox_sum += max(0.0, 1.0 - d / PROX_RANGE)
            self._prox_n += 1
            self._ball_v_sum += ball_speed
            self._ball_v_n += 1
        self._pl_v_sum += mean_player_speed
        self._n += 1
        if self._n >= self.frames_per_bucket:
            return self._close_bucket()
        return None

    # ------------------------------------------------------------------ output
    def _close_bucket(self) -> int:
        t = self._t
        prox = self._prox_sum / self._prox_n if self._prox_n else 0.0
        ball_v = self._ball_v_sum / self._ball_v_n if self._ball_v_n else 0.0
        tempo = 0.5 * min(1.0, ball_v / BALL_SPEED_REF) if self._ball_v_n else 0.0
        tempo += 0.5 * min(1.0, (self._pl_v_sum / self._n) / PLAYER_SPEED_REF)
        threat = 0.0
        for ts, xg, goal in self._shots:
            dt = t - ts
            if dt < 0:
                continue
            threat += SHOT_GAIN * xg * math.exp(-dt / SHOT_TAU)
            if goal:
                threat += GOAL_GAIN * math.exp(-dt / GOAL_TAU)
        self._shots = [s for s in self._shots if t - s[0] < 6 * GOAL_TAU]
        threat = min(1.0, threat)
        while self._changes and t - self._changes[0] > TURNOVER_WINDOW:
            self._changes.popleft()
        turnovers = min(1.0, len(self._changes) / TURNOVER_REF)
        territory = (
            self._territory
            if self._territory is not None
            else self.last_components.get("territory", 0.0)
        )
        comp = {
            "proximity": prox,
            "tempo": tempo,
            "threat": threat,
            "turnovers": turnovers,
            "territory": territory,
        }
        raw = sum(WEIGHTS[k] * v for k, v in comp.items())
        self._smoothed += EMA_ALPHA * (raw - self._smoothed)
        value = index_from_raw(self._smoothed)
        self.series.append(value)
        self.last_components = {k: round(v, 3) for k, v in comp.items()}
        self._reset_bucket()
        return value

    @property
    def current(self) -> int:
        return self.series[-1] if self.series else 0
