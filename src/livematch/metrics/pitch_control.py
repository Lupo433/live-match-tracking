"""Simplified pitch-control model (time-to-intercept, after Spearman 2017).

For every cell of a grid, each player's arrival time is
``reaction_time + |cell - (p + v * reaction_time)| / max_speed``. The control
probability of the home team is a logistic function of the difference between
the fastest away and fastest home arrival times.
"""

from __future__ import annotations

import numpy as np

from livematch.schema import PITCH_LENGTH, PITCH_WIDTH

REACTION_TIME = 0.7  # s
MAX_SPEED = 5.0  # m/s
SIGMA = 0.45  # s, uncertainty of the arrival time


class PitchControl:
    """Pitch control sampled every ``every`` frames (1 s at 25 Hz) for the cumulative
    share; the full grid for display is computed lazily from the latest state."""

    def __init__(self, teams: np.ndarray, nx: int = 32, ny: int = 21, every: int = 25) -> None:
        self.teams = teams
        self.nx, self.ny = nx, ny
        self.every = every
        xs = (np.arange(nx) + 0.5) * PITCH_LENGTH / nx
        ys = (np.arange(ny) + 0.5) * PITCH_WIDTH / ny
        gx, gy = np.meshgrid(xs, ys)  # (ny, nx), row 0 = bottom (y small)
        self.cells = np.stack([gx.ravel(), gy.ravel()], axis=1)  # (ny*nx, 2)
        self._grid: np.ndarray | None = np.full(nx * ny, 0.5)
        self._xy: np.ndarray | None = None
        self._vel: np.ndarray | None = None
        self._frame = 0
        self.sampled_this_frame = False
        self._sum_home = 0.0
        self._samples = 0

    def compute(self, xy: np.ndarray, vel: np.ndarray) -> np.ndarray:
        """Home control probability for every cell (flattened, row-major from y = 0)."""
        valid = np.isfinite(xy).all(axis=1)
        out = np.full(len(self.cells), 0.5)
        home = valid & (self.teams == 0)
        away = valid & (self.teams == 1)
        if not home.any() or not away.any():
            return out
        react = xy + np.nan_to_num(vel) * REACTION_TIME
        t = (
            REACTION_TIME
            + np.linalg.norm(self.cells[:, None, :] - react[None, :, :], axis=2) / MAX_SPEED
        )  # (cells, players)
        t_home = t[:, home].min(axis=1)
        t_away = t[:, away].min(axis=1)
        k = np.pi / (np.sqrt(3.0) * SIGMA)
        return 1.0 / (1.0 + np.exp(-k * (t_away - t_home)))

    def update(self, xy: np.ndarray, vel: np.ndarray, ball_in_play: bool) -> None:
        self._xy, self._vel, self._grid = xy, vel, None
        self._frame += 1
        self.sampled_this_frame = False
        if self._frame % self.every or not ball_in_play:
            return
        self.sampled_this_frame = True
        self._grid = self.compute(xy, vel)
        self._sum_home += float(self._grid.mean())
        self._samples += 1

    @property
    def grid(self) -> np.ndarray:
        """Home control probability of the latest frame (computed on demand)."""
        if self._grid is None:
            assert self._xy is not None and self._vel is not None
            self._grid = self.compute(self._xy, self._vel)
        return self._grid

    def share(self) -> tuple[float, float]:
        if self._samples == 0:
            h = float(self.grid.mean())
            return h, 1 - h
        h = self._sum_home / self._samples
        return h, 1 - h
