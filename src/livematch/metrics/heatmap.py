"""Per-player occupancy heatmaps updated incrementally."""

from __future__ import annotations

import numpy as np

from livematch.schema import PITCH_LENGTH, PITCH_WIDTH


class Heatmaps:
    """Seconds spent by each player in each cell of an ``nx`` x ``ny`` grid."""

    def __init__(self, n: int, fps: float, nx: int = 21, ny: int = 14) -> None:
        self.nx, self.ny = nx, ny
        self.dt = 1.0 / fps
        self.counts = np.zeros((n, ny, nx), dtype=np.float64)

    def cell(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        ix = np.clip((xy[:, 0] / PITCH_LENGTH * self.nx).astype(int), 0, self.nx - 1)
        iy = np.clip((xy[:, 1] / PITCH_WIDTH * self.ny).astype(int), 0, self.ny - 1)
        return ix, iy

    def update(self, xy: np.ndarray) -> None:
        valid = np.flatnonzero(~np.isnan(xy[:, 0]))
        if valid.size == 0:
            return
        pts = xy[valid]
        ix = (pts[:, 0] * (self.nx / PITCH_LENGTH)).astype(np.int64)
        iy = (pts[:, 1] * (self.ny / PITCH_WIDTH)).astype(np.int64)
        np.clip(ix, 0, self.nx - 1, out=ix)
        np.clip(iy, 0, self.ny - 1, out=iy)
        self.counts[valid, iy, ix] += self.dt

    def seconds(self, i: int) -> np.ndarray:
        """Heatmap of player ``i`` (rows = y from bottom, cols = x)."""
        return self.counts[i]
