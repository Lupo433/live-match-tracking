"""A replay session: one data source + a replay clock + the metrics engine.

The session is transport-agnostic: the WebSocket handler calls
:meth:`MatchSession.handle` for client commands and :meth:`MatchSession.tick`
every ~40 ms to obtain the next message to broadcast.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np

from livematch.replay import ReplayClock
from livematch.schema import Event, Frame, Player, match_clock
from livematch.sources.base import DataSource


class Engine(Protocol):
    """Minimal protocol of an incremental metrics engine."""

    def update(self, frame: Frame) -> None: ...
    def snapshot(self) -> dict[str, Any]: ...
    def checkpoint(self) -> Any: ...
    def restore(self, state: Any) -> None: ...


EngineFactory = Callable[[DataSource], Engine]

STATS_EVERY_TICKS = 5  # stats are sent at ~5 Hz, positions at ~25 Hz
CHECKPOINT_EVERY = 1500  # frames (1 minute at 25 Hz)


def _flat(arr: np.ndarray) -> list[float | None]:
    """Round to cm and turn NaN into None (JSON null)."""
    return [None if math.isnan(v) else v for v in np.round(arr, 2).ravel().tolist()]


def player_dict(p: Player) -> dict[str, Any]:
    return {
        "i": p.index,
        "id": p.player_id,
        "team": p.team.value,
        "num": p.number,
        "name": p.name,
        "gk": p.is_goalkeeper,
    }


def event_dict(e: Event) -> dict[str, Any]:
    return {
        "type": e.event_type,
        "sub": e.subtype,
        "team": e.team.value if e.team else None,
        "player": e.player_id,
        "period": e.period,
        "t": round(e.timestamp, 2),
        "f": e.frame_id,
        "x": None if e.x is None else round(e.x, 1),
        "y": None if e.y is None else round(e.y, 1),
        "ex": None if e.end_x is None else round(e.end_x, 1),
        "ey": None if e.end_y is None else round(e.end_y, 1),
        "goal": e.is_goal,
    }


class MatchSession:
    """Replay state for a single client."""

    def __init__(
        self,
        source: DataSource,
        engine_factory: EngineFactory | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.source = source
        self.info = source.info
        self.replay = ReplayClock(self.info.n_frames, self.info.fps, clock=clock)
        self._engine_factory = engine_factory
        self.engine: Engine | None = engine_factory(source) if engine_factory else None
        self.cursor = 0  # next frame the metrics engine has to consume
        self._checkpoints: dict[int, Any] = {}
        self._ticks = 0
        self.selected: int | None = None  # player whose heatmap is streamed
        self._period_start_ts = {
            p: float(source.frame(i).timestamp) for p, i in self.info.period_starts.items()
        }

    # ------------------------------------------------------------------ commands
    def handle(self, msg: dict[str, Any]) -> None:
        """Apply a client command (play, pause, seek, set_speed)."""
        cmd = msg.get("cmd")
        if cmd == "play":
            self.replay.play()
        elif cmd == "pause":
            self.replay.pause()
        elif cmd == "toggle":
            (self.replay.pause if self.replay.playing else self.replay.play)()
        elif cmd == "select_player":
            player = msg.get("player")
            self.selected = None if player is None else int(player)
        elif cmd == "set_speed":
            self.replay.set_speed(float(msg["speed"]))
        elif cmd == "seek":
            if "frame" in msg:
                target = int(msg["frame"])
            elif "minute" in msg:
                target = int(float(msg["minute"]) * 60 * self.info.fps)
            elif "fraction" in msg:
                target = int(float(msg["fraction"]) * (self.info.n_frames - 1))
            else:
                raise ValueError("seek needs frame, minute or fraction")
            self.seek(target)
        else:
            raise ValueError(f"unknown command: {cmd!r}")

    def seek(self, frame: int) -> None:
        frame = min(max(frame, 0), self.info.n_frames - 1)
        self.replay.seek(frame)
        if self.engine is not None and frame < self.cursor:
            # rewind the metrics to the closest checkpoint before the target
            keys = [k for k in self._checkpoints if k <= frame]
            if keys:
                k = max(keys)
                self.engine.restore(self._checkpoints[k])
                self.cursor = k
            else:
                assert self._engine_factory is not None
                self.engine = self._engine_factory(self.source)
                self.cursor = 0

    # ------------------------------------------------------------------ messages
    def init_message(self, matches: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "type": "init",
            "match": self.info.to_dict(),
            "players": [player_dict(p) for p in self.source.players],
            "events": [event_dict(e) for e in self.source.events],
            "matches": matches or [],
            "speeds": [0.5, 1, 2, 5, 10],
        }

    def advance_metrics(self, target: int, budget_s: float = 0.025) -> None:
        """Feed frames ``cursor..target`` to the engine within a time budget."""
        if self.engine is None:
            self.cursor = target + 1
            return
        deadline = time.perf_counter() + budget_s
        n = 0
        while self.cursor <= target:
            self.engine.update(self.source.frame(self.cursor))
            self.cursor += 1
            if self.cursor % CHECKPOINT_EVERY == 0 and self.cursor not in self._checkpoints:
                self._checkpoints[self.cursor] = self.engine.checkpoint()
            n += 1
            if n % 50 == 0 and time.perf_counter() > deadline:
                break

    def tick(self, budget_s: float = 0.025, force_stats: bool = False) -> dict[str, Any]:
        """Advance metrics to the replay position and build the frame message."""
        idx = self.replay.frame_index()
        self.advance_metrics(idx, budget_s)
        frame = self.source.frame(idx)
        self._ticks += 1
        ball = frame.ball
        msg: dict[str, Any] = {
            "type": "frame",
            "f": idx,
            "t": round(frame.timestamp, 2),
            "per": frame.period,
            "clk": match_clock(
                frame.timestamp, frame.period, self._period_start_ts.get(frame.period, 0.0)
            ),
            "pl": _flat(frame.positions),
            "b": None if not frame.ball_visible else _flat(ball),
            "playing": self.replay.playing,
            "speed": self.replay.speed,
            "sync": round(min(1.0, self.cursor / (idx + 1)), 3),
        }
        if self.engine is not None and (force_stats or self._ticks % STATS_EVERY_TICKS == 1):
            msg["st"] = self.engine.snapshot()
            heatmap = getattr(self.engine, "heatmap", None)
            if self.selected is not None and heatmap is not None:
                msg["st"]["heat"] = heatmap(self.selected)
        return msg
