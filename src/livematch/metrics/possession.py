"""Approximate possession from the ball-player proximity."""

from __future__ import annotations

import numpy as np

POSSESSION_RADIUS = 3.0  # metres


class Possession:
    """The team of the closest player within ``radius`` of the ball has possession.

    When nobody is close (passes, clearances) possession stays with the last
    team that had it. Frames without a tracked ball (dead ball) are skipped.
    """

    def __init__(self, teams: np.ndarray, radius: float = POSSESSION_RADIUS) -> None:
        self.teams = teams  # (n,) array of 0 = home, 1 = away
        self.radius = radius
        self.frames = np.zeros(2, dtype=np.int64)
        self.current_team: int | None = None
        self.current_player: int | None = None

    def update(self, xy: np.ndarray, ball: np.ndarray) -> None:
        if not np.isfinite(ball).all():
            self.current_player = None
            return
        diff = xy - ball
        d = diff[:, 0] * diff[:, 0] + diff[:, 1] * diff[:, 1]
        d[np.isnan(d)] = np.inf
        i = int(np.argmin(d))
        if d[i] <= self.radius * self.radius:
            self.current_player = i
            self.current_team = int(self.teams[i])
        else:
            self.current_player = None
        if self.current_team is not None:
            self.frames[self.current_team] += 1

    def share(self) -> tuple[float, float]:
        total = self.frames.sum()
        if total == 0:
            return 0.5, 0.5
        return float(self.frames[0] / total), float(self.frames[1] / total)
