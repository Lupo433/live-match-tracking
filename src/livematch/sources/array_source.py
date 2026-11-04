"""In-memory DataSource backed by numpy arrays (shared by file and synthetic sources)."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from livematch.schema import Event, Frame, MatchInfo, Player
from livematch.sources.base import DataSource


class ArraySource(DataSource):
    """Holds a whole match in memory as dense arrays.

    Args:
        info: match metadata (``n_frames`` must match the arrays).
        players: roster, aligned to axis 1 of ``positions``.
        positions: (n_frames, n_players, 2) metres, NaN when absent.
        ball: (n_frames, 2) metres, NaN when not tracked.
        timestamps: (n_frames,) seconds since kick-off.
        periods: (n_frames,) int period number.
        events: list of events sorted by timestamp.
    """

    def __init__(
        self,
        info: MatchInfo,
        players: list[Player],
        positions: np.ndarray,
        ball: np.ndarray,
        timestamps: np.ndarray,
        periods: np.ndarray,
        events: list[Event],
        cache_key: str | None = None,
    ) -> None:
        n = len(timestamps)
        if positions.shape != (n, len(players), 2) or ball.shape != (n, 2):
            raise ValueError("inconsistent array shapes")
        self._info = info
        self._players = players
        self.positions = np.ascontiguousarray(positions, dtype=np.float64)
        self.ball = np.ascontiguousarray(ball, dtype=np.float64)
        self.timestamps = np.asarray(timestamps, dtype=np.float64)
        self.periods = np.asarray(periods, dtype=np.int64)
        self._events = sorted(events, key=lambda e: e.timestamp)
        self.cache_key = cache_key
        """Fingerprint of the underlying data; enables on-disk caching when set."""

    @property
    def info(self) -> MatchInfo:
        return self._info

    @property
    def players(self) -> list[Player]:
        return self._players

    @property
    def events(self) -> list[Event]:
        return self._events

    def frame(self, frame_id: int) -> Frame:
        if not 0 <= frame_id < len(self.timestamps):
            raise IndexError(frame_id)
        return Frame(
            frame_id=frame_id,
            timestamp=float(self.timestamps[frame_id]),
            period=int(self.periods[frame_id]),
            positions=self.positions[frame_id],
            ball=self.ball[frame_id],
        )

    def frames(self, start: int = 0, stop: int | None = None) -> Iterator[Frame]:
        stop = len(self.timestamps) if stop is None else min(stop, len(self.timestamps))
        for i in range(max(0, start), stop):
            yield self.frame(i)

    def frame_at_time(self, timestamp: float) -> int:
        """Index of the first frame with ``timestamps >= timestamp`` (clamped)."""
        i = int(np.searchsorted(self.timestamps, timestamp, side="left"))
        return min(max(i, 0), len(self.timestamps) - 1)


def period_starts(periods: np.ndarray) -> dict[int, int]:
    """First frame index of every period present in ``periods``."""
    out: dict[int, int] = {}
    for i, p in enumerate(periods):
        if int(p) not in out:
            out[int(p)] = i
    return out
