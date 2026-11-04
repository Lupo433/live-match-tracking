"""A replay session: one data source + a replay clock + the metrics engine.

The session is transport-agnostic: the WebSocket handler calls
:meth:`MatchSession.handle` for client commands and :meth:`MatchSession.tick`
every ~40 ms to obtain the next message to broadcast.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np

from livematch.replay import LiveClock, ReplayClock
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


class CheckpointStore:
    """Metric-engine checkpoints of a whole match, computed once in a background thread.

    Shared by every session replaying the same match: seeking anywhere only
    requires replaying at most ``every`` frames from the closest checkpoint.
    """

    def __init__(
        self, source: DataSource, engine_factory: EngineFactory, every: int = CHECKPOINT_EVERY
    ) -> None:
        self.source = source
        self.engine_factory = engine_factory
        self.every = every
        self._checkpoints: dict[int, Any] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.done = False
        self.loaded_from_cache = False
        self.final_snapshot: dict[str, Any] | None = None

    def start(self) -> CheckpointStore:
        if self._thread is None:
            self._thread = threading.Thread(target=self.run, daemon=True, name="checkpoints")
            self._thread.start()
        return self

    def _cache_key(self) -> str | None:
        from livematch import cache

        key = getattr(self.source, "cache_key", None)
        if key is None or not cache.cache_enabled():
            return None
        return f"{key}-v{cache.CHECKPOINT_CACHE_VERSION}-e{self.every}".replace("/", "_")

    def run(self) -> None:
        from livematch import cache

        key = self._cache_key()
        mid = self.source.info.match_id
        if key is not None:
            data = cache.load_checkpoints(mid, key)
            if data is not None:
                with self._lock:
                    self._checkpoints = dict(data["checkpoints"])
                self.final_snapshot = data["final"]
                self.loaded_from_cache = True
                self.done = True
                return
        engine = self.engine_factory(self.source)
        for i, frame in enumerate(self.source.frames()):
            if i % self.every == 0 and i > 0:
                state = engine.checkpoint()
                with self._lock:
                    self._checkpoints[i] = state
            engine.update(frame)
            if i % 200 == 0:
                time.sleep(0)  # yield the GIL to the event loop
        self.final_snapshot = engine.snapshot()
        with self._lock:
            # full-match state (key = n_frames, never used for seeking): reports reuse it
            self._checkpoints[len(self.source)] = engine.checkpoint()
        self.done = True
        if key is not None:
            try:
                with self._lock:
                    cps = dict(self._checkpoints)
                cache.save_checkpoints(mid, key, {"checkpoints": cps, "final": self.final_snapshot})
            except OSError as exc:
                cache.log.warning("cannot write checkpoint cache: %r", exc)

    def best(self, frame: int) -> tuple[int, Any] | None:
        """Closest checkpoint at or before ``frame`` (state after ``k`` frames)."""
        with self._lock:
            keys = [k for k in self._checkpoints if k <= frame]
            if not keys:
                return None
            k = max(keys)
            return k, self._checkpoints[k]

    def final_state(self) -> Any | None:
        """Engine state after the whole match (available once ``done``)."""
        with self._lock:
            return self._checkpoints.get(len(self.source))

    @property
    def progress(self) -> float:
        with self._lock:
            n = max(self._checkpoints, default=0)
        return 1.0 if self.done else n / max(1, self.source.info.n_frames)


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


def _shot_xg(e: Event) -> float | None:
    """Demonstrative xG of a shot (None for other events)."""
    if e.event_type != "SHOT":
        return None
    from livematch.analytics.geometry import event_start
    from livematch.analytics.models import get_models

    p = event_start(e)
    return None if p is None else round(get_models().xg.predict(*p), 3)


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
        "gf": e.goal_frame,
        "to": e.to_player_id,
        "xg": _shot_xg(e),
    }


class MatchSession:
    """Replay state for a single client."""

    def __init__(
        self,
        source: DataSource,
        engine_factory: EngineFactory | None = None,
        clock: Callable[[], float] = time.monotonic,
        store: CheckpointStore | None = None,
    ) -> None:
        self.source = source
        self.info = source.info
        self.is_live = source.info.source == "live"
        self.replay: ReplayClock | LiveClock
        if self.is_live:
            self.replay = LiveClock(lambda: len(source), self.info.fps, clock=clock)
        else:
            self.replay = ReplayClock(self.info.n_frames, self.info.fps, clock=clock)
        self._events_sent = len(source.events)
        self._engine_factory = engine_factory
        self.engine: Engine | None = engine_factory(source) if engine_factory else None
        self.cursor = 0  # next frame the metrics engine has to consume
        self._checkpoints: dict[int, Any] = {}
        self.store = store
        self._ticks = 0
        self.selected: int | None = None  # player whose heatmap is streamed
        self._period_start_ts: dict[int, float] = {}
        self._refresh_periods()

    def _refresh_periods(self) -> None:
        for p, i in self.source.info.period_starts.items():
            if p not in self._period_start_ts:
                # a live feed may be joined mid-half: provider timestamps count from
                # kick-off, so the first half always starts at t = 0
                live_first_half = self.is_live and p == 1
                self._period_start_ts[p] = (
                    0.0 if live_first_half else float(self.source.frame(i).timestamp)
                )

    # ------------------------------------------------------------------ commands
    def handle(self, msg: dict[str, Any]) -> None:
        """Apply a client command (play, pause, seek, set_speed)."""
        cmd = msg.get("cmd")
        if cmd == "play":
            self.replay.play()
        elif cmd == "pause":
            self.replay.pause()
        elif cmd == "go_live":
            if isinstance(self.replay, LiveClock):
                self.replay.go_live()
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
                target = int(float(msg["fraction"]) * (len(self.source) - 1))
            else:
                raise ValueError("seek needs frame, minute or fraction")
            self.seek(target)
        else:
            raise ValueError(f"unknown command: {cmd!r}")

    def seek(self, frame: int) -> None:
        frame = min(max(frame, 0), len(self.source) - 1)
        self.replay.seek(frame)
        frame = self.replay.frame_index()
        if self.engine is None:
            return
        # closest known state at or before the target (own or shared checkpoints)
        candidates = [(k, st) for k, st in self._checkpoints.items() if k <= frame]
        if self.store is not None and (shared := self.store.best(frame)) is not None:
            candidates.append(shared)
        best = max(candidates, key=lambda c: c[0], default=None)
        if frame < self.cursor:
            if best is not None:
                self.engine.restore(best[1])
                self.cursor = best[0]
            else:
                assert self._engine_factory is not None
                self.engine = self._engine_factory(self.source)
                self.cursor = 0
        elif best is not None and best[0] > self.cursor:
            # jump forward without replaying every intermediate frame
            self.engine.restore(best[1])
            self.cursor = best[0]

    # ------------------------------------------------------------------ messages
    def init_message(self, matches: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        events = list(self.source.events)
        self._events_sent = len(events)
        return {
            "type": "init",
            "match": self.source.info.to_dict(),
            "players": [player_dict(p) for p in self.source.players],
            "events": [event_dict(e) for e in events],
            "matches": matches or [],
            "speeds": [0.5, 1, 2, 5, 10],
            "live": self.is_live,
        }

    def advance_metrics(self, target: int, budget_s: float = 0.025) -> None:
        """Feed frames ``cursor..target`` to the engine within a time budget."""
        if self.engine is None:
            self.cursor = target + 1
            return
        if self.store is not None and target - self.cursor > self.store.every:
            # the shared background pass may have reached a closer checkpoint meanwhile
            shared = self.store.best(target)
            if shared is not None and shared[0] > self.cursor:
                self.engine.restore(shared[1])
                self.cursor = shared[0]
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
        if len(self.source) == 0:
            return {"type": "waiting"}
        idx = min(idx, len(self.source) - 1)
        self.advance_metrics(idx, budget_s)
        frame = self.source.frame(idx)
        if frame.period not in self._period_start_ts:
            self._refresh_periods()
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
            "n": len(self.source),
        }
        if isinstance(self.replay, LiveClock):
            msg["live"] = True
            msg["at_edge"] = self.replay.is_live
            msg["lag"] = round(self.replay.lag_frames() / self.info.fps, 1)
            events = self.source.events
            if len(events) > self._events_sent:
                msg["ev"] = [event_dict(e) for e in events[self._events_sent :]]
                self._events_sent = len(events)
        if self.engine is not None and (force_stats or self._ticks % STATS_EVERY_TICKS == 1):
            msg["st"] = self.engine.snapshot()
            heatmap = getattr(self.engine, "heatmap", None)
            if self.selected is not None and heatmap is not None:
                msg["st"]["heat"] = heatmap(self.selected)
        return msg
