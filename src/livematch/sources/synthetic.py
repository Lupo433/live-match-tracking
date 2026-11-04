"""Synthetic but plausible match generator (fallback source and test fixture).

Model, per frame at 25 Hz:
    * Each team plays a 4-4-2 block. A player's target is its formation slot,
      shifted towards the ball and compressed/expanded with the ball position.
    * The closest player of each team chases the ball.
    * Players accelerate towards their target with bounded acceleration and a
      per-player top speed (7.5-9 m/s) so sprints and HI runs occur.
    * The ball is carried by its owner and passed every 1-4 s at 12-20 m/s;
      sometimes the pass is intercepted, sometimes there is a shot.
"""

from __future__ import annotations

import numpy as np

from livematch.schema import (
    DEFAULT_FPS,
    PITCH_LENGTH,
    PITCH_WIDTH,
    Event,
    MatchInfo,
    Player,
    Team,
)
from livematch.sources.array_source import ArraySource, period_starts

# 4-4-2 slots for a team attacking left -> right, as fractions of the pitch.
_FORMATION = np.array(
    [
        [0.05, 0.50],  # GK
        [0.22, 0.15],
        [0.20, 0.38],
        [0.20, 0.62],
        [0.22, 0.85],
        [0.40, 0.12],
        [0.38, 0.40],
        [0.38, 0.60],
        [0.40, 0.88],
        [0.55, 0.40],
        [0.55, 0.60],
    ]
)
_NUMBERS = [1, 2, 5, 4, 3, 7, 8, 6, 11, 9, 10]


def _roster() -> list[Player]:
    players: list[Player] = []
    for t_i, team in enumerate((Team.HOME, Team.AWAY)):
        for k, num in enumerate(_NUMBERS):
            idx = t_i * 11 + k
            players.append(
                Player(
                    index=idx,
                    player_id=f"{team.value[0].upper()}{num}",
                    team=team,
                    number=num,
                    name=f"{team.value.title()} #{num}",
                    is_goalkeeper=(k == 0),
                )
            )
    return players


def generate_synthetic(
    duration_s: float = 600.0,
    fps: float = DEFAULT_FPS,
    seed: int = 7,
    match_id: str = "synthetic",
) -> ArraySource:
    """Generate a full synthetic match of ``duration_s`` seconds (two halves)."""
    rng = np.random.default_rng(seed)
    n = int(round(duration_s * fps))
    dt = 1.0 / fps
    players = _roster()
    n_p = len(players)
    dims = np.array([PITCH_LENGTH, PITCH_WIDTH])

    # formation in metres for each player, home attacks +x, away mirrored.
    base = np.zeros((n_p, 2))
    base[:11] = _FORMATION * dims
    base[11:] = (1 - _FORMATION) * dims
    attack_dir = np.array([1.0] * 11 + [-1.0] * 11)
    top_speed = rng.uniform(7.6, 9.0, n_p)
    top_speed[[0, 11]] = 6.0

    pos = base.copy()
    vel = np.zeros((n_p, 2))
    positions = np.empty((n, n_p, 2))
    ball_arr = np.empty((n, 2))
    periods = np.where(np.arange(n) < n // 2, 1, 2)
    timestamps = np.arange(n) * dt
    events: list[Event] = []

    owner = 9  # home striker kicks off
    ball = np.array([PITCH_LENGTH / 2, PITCH_WIDTH / 2])
    pos[owner] = ball + np.array([-0.5, 0.0])
    flight: tuple[np.ndarray, np.ndarray, int, int] | None = None  # from, to, t0, t1
    next_action = int(rng.uniform(1.0, 3.0) * fps)
    wander = np.zeros((n_p, 2))
    next_restart: tuple[int, int] | None = None

    for f in range(n):
        if f == n // 2:  # second half kick-off: reset shape, away kicks off
            pos = base.copy()
            vel[:] = 0
            owner, flight, next_restart = 20, None, None
            ball = np.array([PITCH_LENGTH / 2, PITCH_WIDTH / 2])
        if next_restart is not None and f >= next_restart[0]:
            owner, flight = next_restart[1], None
            ball = np.array([PITCH_LENGTH / 2, PITCH_WIDTH / 2])
            pos[owner] = ball
            next_action = f + int(2 * fps)
            next_restart = None
        # ---- ball dynamics
        if flight is not None:
            p0, p1, t0, t1 = flight
            a = (f - t0) / max(1, t1 - t0)
            ball = p0 + (p1 - p0) * min(a, 1.0)
            if a >= 1.0 and next_restart is None:
                flight = None
                d = np.linalg.norm(pos - ball, axis=1)
                owner = int(np.argmin(d))
                next_action = f + int(rng.uniform(1.0, 4.0) * fps)
        elif owner >= 0:
            ball = pos[owner] + vel[owner] * 0.12
            if f >= next_action:
                team_slice = slice(0, 11) if owner < 11 else slice(11, 22)
                own_dir = attack_dir[owner]
                goal = np.array([PITCH_LENGTH if own_dir > 0 else 0.0, PITCH_WIDTH / 2])
                dist_goal = np.linalg.norm(goal - ball)
                team = Team.HOME if owner < 11 else Team.AWAY
                if dist_goal < 28 and rng.random() < 0.45:
                    # shot
                    target = goal + np.array([0.0, rng.normal(0, 4.5)])
                    scored = abs(target[1] - PITCH_WIDTH / 2) < 3.4 and rng.random() < 0.35
                    sub = "ON TARGET-GOAL" if scored else "OFF TARGET-OUT"
                    events.append(
                        _event(
                            "SHOT", sub, team, players[owner], f, ball, target, fps, int(periods[f])
                        )
                    )
                    if scored:  # ball goes in, then back to the centre spot
                        flight = (ball.copy(), target, f, f + int(dist_goal / 25 * fps) + 1)
                        restart_owner = 20 if owner < 11 else 9
                        next_restart = (f + int(4 * fps), restart_owner)
                    else:  # goal kick: the keeper collects the ball
                        keeper = 11 if own_dir > 0 else 0
                        flight = (ball.copy(), pos[keeper].copy(), f, f + int(2 * fps))
                    owner = -1
                else:
                    mates = [i for i in range(team_slice.start, team_slice.stop) if i != owner]
                    fwd = np.array([attack_dir[i] * (pos[i, 0] - ball[0]) for i in mates])
                    w = np.exp(np.clip(fwd, -30, 30) / 15.0)
                    recv = int(rng.choice(mates, p=w / w.sum()))
                    target = pos[recv] + vel[recv] * 0.6
                    if rng.random() < 0.22:  # inaccurate pass, likely intercepted
                        target = target + rng.normal(0, 8, 2)
                    target = np.clip(target, [1, 1], dims - 1)
                    speed = rng.uniform(12, 20)
                    dur = max(2, int(np.linalg.norm(target - ball) / speed * fps))
                    events.append(
                        _event(
                            "PASS", "", team, players[owner], f, ball, target, fps, int(periods[f])
                        )
                    )
                    flight = (ball.copy(), target, f, f + dur)
                    owner = -1
        ball = np.clip(ball, [0, 0], dims)

        # ---- player dynamics
        shift_x = (ball[0] - PITCH_LENGTH / 2) * 0.55
        shift_y = (ball[1] - PITCH_WIDTH / 2) * 0.35
        target = base + np.array([shift_x, 0.0])
        target[:, 1] = PITCH_WIDTH / 2 + (base[:, 1] - PITCH_WIDTH / 2) * 0.85 + shift_y
        target[[0, 11], 0] = base[[0, 11], 0] + shift_x * 0.15
        wander += rng.normal(0, 0.15, wander.shape) - wander * 0.01
        target += wander
        for t_i in (0, 1):
            sl = slice(t_i * 11 + 1, t_i * 11 + 11)  # outfield
            d = np.linalg.norm(pos[sl] - ball, axis=1)
            chaser = t_i * 11 + 1 + int(np.argmin(d))
            if chaser != owner:
                target[chaser] = ball + (vel[chaser] * 0.0)
        if owner >= 0:  # dribble towards goal
            target[owner] = pos[owner] + np.array([attack_dir[owner] * 6.0, rng.normal(0, 2)])
        desired = target - pos
        dist = np.linalg.norm(desired, axis=1, keepdims=True)
        want = desired / np.maximum(dist, 1e-6) * np.minimum(top_speed[:, None], dist * 1.2)
        acc = (want - vel) / dt
        acc_n = np.linalg.norm(acc, axis=1, keepdims=True)
        acc = acc / np.maximum(acc_n, 1e-6) * np.minimum(acc_n, 6.0)
        vel = vel + acc * dt
        pos = np.clip(pos + vel * dt, [-1.0, -1.0], dims + 1.0)

        positions[f] = pos
        ball_arr[f] = ball

    info = MatchInfo(
        match_id=match_id,
        title="Synthetic match (generated)",
        home_name="Home",
        away_name="Away",
        fps=fps,
        n_frames=n,
        duration_s=n / fps,
        period_starts=period_starts(periods),
        source="synthetic",
    )
    return ArraySource(info, players, positions, ball_arr, timestamps, periods, events)


def _event(
    etype: str,
    subtype: str,
    team: Team,
    player: Player,
    f: int,
    start: np.ndarray,
    end: np.ndarray,
    fps: float,
    period: int,
) -> Event:
    return Event(
        event_type=etype,
        subtype=subtype,
        team=team,
        player_id=player.player_id,
        period=period,
        timestamp=f / fps,
        frame_id=f,
        x=float(start[0]),
        y=float(start[1]),
        end_x=float(end[0]),
        end_y=float(end[1]),
    )


class SyntheticSource(ArraySource):
    """Convenience wrapper: ``SyntheticSource(duration_s=...)``."""

    def __init__(
        self,
        duration_s: float = 600.0,
        fps: float = DEFAULT_FPS,
        seed: int = 7,
        match_id: str = "synthetic",
    ) -> None:
        src = generate_synthetic(duration_s, fps, seed, match_id)
        super().__init__(
            src.info, src.players, src.positions, src.ball, src.timestamps, src.periods, src.events
        )
