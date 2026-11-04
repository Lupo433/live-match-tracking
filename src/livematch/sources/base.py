"""Abstract data-source interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from livematch.schema import Event, Frame, MatchInfo, Player, Team


class DataSource(ABC):
    """A provider of tracking frames and match events.

    Implementations: Metrica CSV files, synthetic generator, live feed stub.
    The replay engine, metrics and API only ever talk to this interface.
    """

    cache_key: str | None = None
    """Stable fingerprint of the data (``None`` = not cacheable, e.g. live feeds)."""

    @property
    @abstractmethod
    def info(self) -> MatchInfo:
        """Static match metadata."""

    @property
    @abstractmethod
    def players(self) -> list[Player]:
        """Roster; ``players[i].index == i`` and aligns with ``Frame.positions``."""

    @property
    @abstractmethod
    def events(self) -> list[Event]:
        """All known events, sorted by timestamp (may grow for live sources)."""

    @abstractmethod
    def frame(self, frame_id: int) -> Frame:
        """Random access to a single frame (needed for seek)."""

    def __len__(self) -> int:
        return self.info.n_frames

    def frames(self, start: int = 0, stop: int | None = None) -> Iterator[Frame]:
        """Iterate frames in ``[start, stop)``. Override for faster sequential access."""
        stop = len(self) if stop is None else min(stop, len(self))
        for i in range(max(0, start), stop):
            yield self.frame(i)

    def team_players(self, team: Team) -> list[Player]:
        return [p for p in self.players if p.team == team]
