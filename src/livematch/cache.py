"""On-disk cache for converted matches and metric checkpoints.

Layout (default root: ``<project>/.cache``, override with ``LIVEMATCH_CACHE_DIR``,
disable with ``LIVEMATCH_CACHE=0``)::

    .cache/sources/<match_id>-<key>.npz        converted tracking arrays + metadata
    .cache/checkpoints/<match_id>-<key>.pkl    metric-engine checkpoints of a match

``key`` is a fingerprint of the source files (path, size, mtime) plus a
format version, so editing/replacing a CSV invalidates the cache. Corrupted
files are ignored and rewritten. Writes are atomic (temp file + rename).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from livematch.schema import Event, MatchInfo, Player, Team

log = logging.getLogger("livematch.cache")

SOURCE_CACHE_VERSION = "3"
CHECKPOINT_CACHE_VERSION = "3"  # bump when the metrics engine state changes


def cache_enabled() -> bool:
    return os.environ.get("LIVEMATCH_CACHE", "1") != "0"


def cache_root() -> Path:
    from livematch.catalog import PROJECT_ROOT

    return Path(os.environ.get("LIVEMATCH_CACHE_DIR", PROJECT_ROOT / ".cache"))


def fingerprint(paths: list[Path], extra: str = "") -> str:
    """Short hash of file paths, sizes and modification times."""
    h = hashlib.sha256(extra.encode())
    for p in sorted(paths):
        st = p.stat()
        h.update(f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode())
    return h.hexdigest()[:16]


def _atomic_write(path: Path, write) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            write(fh)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _remove_stale(directory: Path, match_id: str, keep: Path) -> None:
    for old in directory.glob(f"{match_id}-*"):
        if old != keep:
            old.unlink(missing_ok=True)


# ---------------------------------------------------------------------- sources
def source_path(match_id: str, key: str) -> Path:
    return cache_root() / "sources" / f"{match_id}-{key}.npz"


def save_source(src: Any, key: str) -> Path:
    """Persist an :class:`ArraySource` as a compressed npz."""
    meta = {
        "info": src.info.to_dict(),
        "players": [{**asdict(p), "team": p.team.value} for p in src.players],
        "events": [{**asdict(e), "team": e.team.value if e.team else None} for e in src.events],
    }
    path = source_path(src.info.match_id, key)

    def write(fh) -> None:
        np.savez_compressed(
            fh,
            positions=src.positions.astype(np.float32),
            ball=src.ball.astype(np.float32),
            timestamps=src.timestamps,
            periods=src.periods,
            meta=np.frombuffer(json.dumps(meta).encode(), dtype=np.uint8),
        )

    _atomic_write(path, write)
    _remove_stale(path.parent, src.info.match_id, path)
    return path


def load_source(match_id: str, key: str):
    """Load a cached source, or ``None`` on miss / corruption."""
    from livematch.sources.array_source import ArraySource

    path = source_path(match_id, key)
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=False) as z:
            meta = json.loads(z["meta"].tobytes().decode())
            positions = z["positions"].astype(np.float64)
            ball = z["ball"].astype(np.float64)
            timestamps = z["timestamps"]
            periods = z["periods"]
        info_d = meta["info"]
        info_d["period_starts"] = {int(k): v for k, v in info_d["period_starts"].items()}
        info = MatchInfo(**info_d)
        players = [Player(**{**p, "team": Team(p["team"])}) for p in meta["players"]]
        events = [
            Event(**{**e, "team": Team(e["team"]) if e["team"] else None}) for e in meta["events"]
        ]
        return ArraySource(info, players, positions, ball, timestamps, periods, events)
    except Exception as exc:  # corrupted / incompatible file
        log.warning("ignoring corrupted cache %s: %r", path, exc)
        path.unlink(missing_ok=True)
        return None


# ---------------------------------------------------------------------- checkpoints
def checkpoint_path(match_id: str, key: str) -> Path:
    return cache_root() / "checkpoints" / f"{match_id}-{key}.pkl"


def save_checkpoints(match_id: str, key: str, data: dict[str, Any]) -> Path:
    path = checkpoint_path(match_id, key)
    _atomic_write(path, lambda fh: pickle.dump(data, fh, protocol=pickle.HIGHEST_PROTOCOL))
    _remove_stale(path.parent, match_id, path)
    return path


def load_checkpoints(match_id: str, key: str) -> dict[str, Any] | None:
    """Checkpoint bundle ``{"checkpoints": {...}, "final": snapshot}`` or ``None``.

    Only files written by this application in its own cache directory are
    unpickled.
    """
    path = checkpoint_path(match_id, key)
    if not path.exists():
        return None
    try:
        with path.open("rb") as fh:
            data = pickle.load(fh)
        if not isinstance(data, dict) or "checkpoints" not in data or "final" not in data:
            raise ValueError("unexpected checkpoint bundle")
        return data
    except Exception as exc:
        log.warning("ignoring corrupted checkpoint cache %s: %r", path, exc)
        path.unlink(missing_ok=True)
        return None
