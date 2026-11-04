"""Discovery and lazy loading of the matches available to the server."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from livematch.sources.base import DataSource

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """Root data directory (override with the LIVEMATCH_DATA_DIR env var)."""
    return Path(os.environ.get("LIVEMATCH_DATA_DIR", PROJECT_ROOT / "data"))


@dataclass(frozen=True)
class MatchEntry:
    match_id: str
    title: str
    loader: Callable[[], DataSource]


class Catalog:
    """Registry of available matches; sources are loaded once and cached."""

    def __init__(self, entries: list[MatchEntry]) -> None:
        self._entries = {e.match_id: e for e in entries}
        self._cache: dict[str, DataSource] = {}
        self._lock = threading.Lock()

    def list(self) -> list[MatchEntry]:
        return list(self._entries.values())

    def __contains__(self, match_id: str) -> bool:
        return match_id in self._entries

    def get(self, match_id: str) -> DataSource:
        if match_id not in self._entries:
            raise KeyError(match_id)
        with self._lock:
            if match_id not in self._cache:
                self._cache[match_id] = self._entries[match_id].loader()
            return self._cache[match_id]

    @property
    def default_id(self) -> str:
        """Prefer a full real match, then the sample, then synthetic."""
        for mid in ("metrica_game_1", "metrica_game_2", "sample_game_1", "synthetic"):
            if mid in self._entries:
                return mid
        return next(iter(self._entries))


def default_catalog(base: Path | None = None) -> Catalog:
    """Build the catalog from what exists on disk (synthetic is always present)."""
    from livematch.sources.metrica import load_metrica_cached
    from livematch.sources.synthetic import SyntheticSource

    base = base or data_dir()
    entries: list[MatchEntry] = []
    raw = base / "raw" / "metrica" / "data"
    for g in (1, 2):
        d = raw / f"Sample_Game_{g}"
        if (d / f"Sample_Game_{g}_RawTrackingData_Home_Team.csv").exists():
            mid = f"metrica_game_{g}"
            entries.append(
                MatchEntry(
                    mid,
                    f"Metrica Sample Game {g} (full match)",
                    lambda d=d, mid=mid, g=g: load_metrica_cached(
                        d, mid, f"Metrica Sample Game {g}"
                    ),
                )
            )
    sample = base / "sample" / "Sample_Game_1"
    if sample.exists():
        entries.append(
            MatchEntry(
                "sample_game_1",
                "Metrica Game 1 - 2 min sample",
                lambda: load_metrica_cached(sample, "sample_game_1", "Metrica Game 1 (sample)"),
            )
        )
    entries.append(
        MatchEntry(
            "synthetic",
            "Synthetic match (10 min)",
            lambda: SyntheticSource(duration_s=600.0, match_id="synthetic"),
        )
    )
    return Catalog(entries)
