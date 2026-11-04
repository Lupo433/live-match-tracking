"""Incremental metrics engine: composes all metric components."""

from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np

from livematch.metrics.events import EventTracker
from livematch.metrics.heatmap import Heatmaps
from livematch.metrics.kinematics import (
    HI_SPEED,
    SPRINT_SPEED,
    EffortTracker,
    Kinematics,
    PointKinematics,
)
from livematch.metrics.pitch_control import PitchControl
from livematch.metrics.possession import Possession
from livematch.metrics.shape import ShapeValues, TeamShape
from livematch.schema import Event, Frame, Player, Team
from livematch.sources.base import DataSource

MAX_BALL_SPEED = 45.0  # m/s
SHAPE_EVERY = 5  # team shape sampled at 5 Hz


def _r(v: float, nd: int = 2) -> float | None:
    return None if v is None or not math.isfinite(v) else round(float(v), nd)


class MetricsEngine:
    """Consumes frames one by one and keeps every statistic up to date.

    Nothing is ever recomputed from scratch: each component keeps a small
    state that is updated in O(players) per frame (pitch control in
    O(cells x players) every few frames).
    """

    def __init__(self, players: list[Player], fps: float, events: list[Event] | None = None):
        self.players = players
        self.fps = fps
        n = len(players)
        self.teams = np.array([0 if p.team == Team.HOME else 1 for p in players])
        self.kin = Kinematics(n, fps)
        self.sprint = EffortTracker(n, fps, SPRINT_SPEED)
        self.hi = EffortTracker(n, fps, HI_SPEED)
        self.heat = Heatmaps(n, fps)
        self.possession = Possession(self.teams)
        self.pitch_control = PitchControl(self.teams)
        gk = np.array([p.is_goalkeeper for p in players])
        self.shapes = {
            Team.HOME: TeamShape(np.flatnonzero((self.teams == 0) & ~gk), attacks_right=True),
            Team.AWAY: TeamShape(np.flatnonzero((self.teams == 1) & ~gk), attacks_right=False),
        }
        self.ball = PointKinematics(fps, max_speed=MAX_BALL_SPEED)
        self.events = EventTracker(events or [])
        self.on_pitch = np.zeros(n, dtype=bool)
        self.frames_seen = 0
        self.last_frame_id = -1

    @classmethod
    def for_source(cls, source: DataSource) -> MetricsEngine:
        return cls(source.players, source.info.fps, source.events)

    # ------------------------------------------------------------------ update
    def update(self, frame: Frame) -> None:
        xy = frame.positions
        self.on_pitch = ~np.isnan(xy[:, 0])
        self.kin.update(xy, frame.period)
        # efforts pair each smoothed speed with the step of the same (centre) frame
        self.sprint.update(self.kin.speed, self.kin.centre_step)
        self.hi.update(self.kin.speed, self.kin.centre_step)
        self.heat.update(xy)
        self.possession.update(xy, frame.ball)
        in_play = frame.ball_visible
        self.pitch_control.update(xy, self.kin.velocity, in_play)
        if in_play and self.frames_seen % SHAPE_EVERY == 0:
            for shape in self.shapes.values():
                shape.update(xy)
        self.ball.update(float(frame.ball[0]), float(frame.ball[1]), frame.period)
        self.events.update(frame.frame_id)
        self.frames_seen += 1
        self.last_frame_id = frame.frame_id

    # ------------------------------------------------------------------ state
    def checkpoint(self) -> dict[str, Any]:
        state = {k: v for k, v in self.__dict__.items() if k not in ("players",)}
        return copy.deepcopy(state)

    def restore(self, state: dict[str, Any]) -> None:
        self.__dict__.update(copy.deepcopy(state))

    # ------------------------------------------------------------------ output
    def team_totals(self, team: Team) -> dict[str, Any]:
        mask = self.teams == (0 if team == Team.HOME else 1)
        shape: ShapeValues = self.shapes[team].current
        avg: ShapeValues = self.shapes[team].average()
        out: dict[str, Any] = {
            "dist_km": _r(self.kin.distance[mask].sum() / 1000, 3),
            "sprints": int(self.sprint.count[mask].sum()),
            "sprint_m": _r(self.sprint.distance[mask].sum(), 0),
            "hi_runs": int(self.hi.count[mask].sum()),
            "hi_m": _r(self.hi.distance[mask].sum(), 0),
            "cx": _r(shape.cx, 1),
            "cy": _r(shape.cy, 1),
            "width": _r(shape.width, 1),
            "length": _r(shape.length, 1),
            "line": _r(shape.line, 1),
            "avg_width": _r(avg.width, 1),
            "avg_length": _r(avg.length, 1),
            "avg_line": _r(avg.line, 1),
        }
        out.update(self.events.counts[team.value])
        return out

    def player_rows(self) -> list[list[Any]]:
        """``[index, dist_m, speed, max_speed, sprints, hi_m, on_pitch]`` per player seen."""
        rows = []
        for p in self.players:
            i = p.index
            if self.kin.distance[i] == 0 and not self.on_pitch[i]:
                continue  # unused substitute
            rows.append(
                [
                    i,
                    round(float(self.kin.distance[i]), 1),
                    round(float(self.kin.speed[i]), 2),
                    round(float(self.kin.max_speed_reached[i]), 2),
                    int(self.sprint.count[i]),
                    round(float(self.hi.distance[i]), 1),
                    bool(self.on_pitch[i]),
                ]
            )
        return rows

    def snapshot(self) -> dict[str, Any]:
        ph, pa = self.possession.share()
        ch, ca = self.pitch_control.share()
        grid = np.round(self.pitch_control.grid * 100).astype(int).tolist()
        return {
            "frame": self.last_frame_id,
            "poss": {"home": round(ph, 4), "away": round(pa, 4)},
            "pc": {
                "home": round(ch, 4),
                "away": round(ca, 4),
                "grid": {"nx": self.pitch_control.nx, "ny": self.pitch_control.ny, "v": grid},
            },
            "teams": {"home": self.team_totals(Team.HOME), "away": self.team_totals(Team.AWAY)},
            "ball": {
                "v": round(self.ball.speed, 2),
                "vmax": round(self.ball.max_speed_reached, 2),
            },
            "own": self.possession.current_player,
            "players": self.player_rows(),
        }

    def heatmap(self, i: int) -> dict[str, Any]:
        """Heatmap of player ``i`` in seconds, row-major from y = 0."""
        h = self.heat.seconds(i)
        return {
            "i": i,
            "nx": self.heat.nx,
            "ny": self.heat.ny,
            "v": np.round(h, 2).ravel().tolist(),
        }
