"""Team shape: centroid, width, length and defensive-line height."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from livematch.schema import PITCH_LENGTH

DEF_LINE_PLAYERS = 4


@dataclass
class ShapeValues:
    cx: float = float("nan")
    cy: float = float("nan")
    width: float = float("nan")
    length: float = float("nan")
    line: float = float("nan")


def team_shape(xy: np.ndarray, attacks_right: bool) -> ShapeValues:
    """Shape of a set of outfield positions (NaN rows ignored).

    ``line`` is the distance from the team's own goal line of the mean x of its
    ``DEF_LINE_PLAYERS`` deepest outfield players.
    """
    pts = xy[np.isfinite(xy).all(axis=1)]
    if len(pts) < 2:
        return ShapeValues()
    x, y = pts[:, 0], pts[:, 1]
    depth = x if attacks_right else PITCH_LENGTH - x
    k = min(DEF_LINE_PLAYERS, len(depth))
    line = float(np.mean(np.sort(depth)[:k]))
    return ShapeValues(
        cx=float(x.mean()),
        cy=float(y.mean()),
        width=float(y.max() - y.min()),
        length=float(x.max() - x.min()),
        line=line,
    )


class TeamShape:
    """Instantaneous shape (exponentially smoothed) and running average."""

    def __init__(self, outfield_idx: np.ndarray, attacks_right: bool, alpha: float = 0.3):
        self.idx = outfield_idx
        self.attacks_right = attacks_right
        self.alpha = alpha  # EMA weight per sample
        self.current = ShapeValues()
        self._sum = np.zeros(5)
        self._n = 0

    def update(self, xy: np.ndarray) -> None:
        v = team_shape(xy[self.idx], self.attacks_right)
        new = np.array([v.cx, v.cy, v.width, v.length, v.line])
        if not np.isfinite(new).all():
            return
        cur = np.array(
            [
                self.current.cx,
                self.current.cy,
                self.current.width,
                self.current.length,
                self.current.line,
            ]
        )
        cur = new if not np.isfinite(cur).all() else cur + self.alpha * (new - cur)
        self.current = ShapeValues(*map(float, cur))
        self._sum += new
        self._n += 1

    def average(self) -> ShapeValues:
        if self._n == 0:
            return ShapeValues()
        return ShapeValues(*map(float, self._sum / self._n))
