"""Fake live tracking provider.

Streams a recorded match over WebSocket at real time, in a wire format that is
deliberately DIFFERENT from the internal schema, to exercise a real adapter:

* opaque provider player ids (``"pl_3f9a1c"``), team codes ``"H"``/``"A"``;
* coordinates normalised to [0, 1] with the origin in the TOP-left corner and
  in "stadium" orientation (teams swap sides at half time, nobody normalises
  the attacking direction for you);
* timestamps in integer milliseconds since kick-off, a sequence number per frame;
* only the players on the pitch are listed; the ball is ``null`` when lost.

Messages::

    {"type": "lineup", "match": str, "fps": 25, "teams": {"H": {...}, "A": {...}},
     "players": [{"pid": str, "team": "H", "shirt": 11, "role": "GK"}, ...]}
    {"type": "tracking", "seq": int, "ts_ms": int, "half": 1,
     "ball": {"x": float, "y": float} | null, "objs": [{"pid": str, "x": float, "y": float}]}
    {"type": "event", "seq": int, "ts_ms": int, "kind": "SHOT", "detail": "ON TARGET-GOAL",
     "team": "H", "pid": str | null, "x": float | null, "y": float | null}

Network impairments (all optional): constant delay, packet loss, out-of-order
delivery and periodic disconnections.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from livematch.schema import PITCH_LENGTH, PITCH_WIDTH, Team
from livematch.sources.array_source import ArraySource


def provider_pid(player_id: str) -> str:
    """Opaque, stable provider id for one of our players."""
    return "pl_" + hashlib.sha1(player_id.encode()).hexdigest()[:6]


@dataclass
class Impairments:
    """Network conditions to simulate."""

    delay_ms: float = 0.0
    drop_prob: float = 0.0
    reorder_prob: float = 0.0
    disconnect_every_s: float = 0.0
    seed: int = 0


def to_raw(x: float, y: float, half: int) -> tuple[float, float] | None:
    """Internal metres (home attacks right) -> provider stadium coordinates."""
    if math.isnan(x) or math.isnan(y):
        return None
    xn, yn = x / PITCH_LENGTH, 1.0 - y / PITCH_WIDTH
    if half % 2 == 0:  # teams swap sides in the second half
        xn, yn = 1.0 - xn, 1.0 - yn
    return round(xn, 5), round(yn, 5)


class FakeProvider:
    """Generates provider messages from an :class:`ArraySource` on a live clock."""

    def __init__(
        self,
        source: ArraySource,
        speed: float = 1.0,
        start_frame: int = 0,
        impairments: Impairments | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.source = source
        self.fps = source.info.fps
        self.speed = speed
        self.start_frame = start_frame
        self.imp = impairments or Impairments()
        self._clock = clock
        self._t0 = clock()
        self._pids = [provider_pid(p.player_id) for p in source.players]
        self._events_by_frame: dict[int, list] = {}
        for e in source.events:
            self._events_by_frame.setdefault(e.frame_id, []).append(e)

    # ------------------------------------------------------------------ clock
    def live_frame(self) -> int:
        """Latest frame "happening" now in the stadium (minus the network delay)."""
        elapsed = self._clock() - self._t0 - self.imp.delay_ms / 1000.0
        f = self.start_frame + int(max(0.0, elapsed) * self.fps * self.speed)
        return min(f, len(self.source) - 1)

    @property
    def finished(self) -> bool:
        return self.live_frame() >= len(self.source) - 1

    # ------------------------------------------------------------------ messages
    def lineup_message(self) -> dict[str, Any]:
        return {
            "type": "lineup",
            "match": self.source.info.match_id,
            "fps": self.fps,
            "teams": {
                "H": {"name": self.source.info.home_name},
                "A": {"name": self.source.info.away_name},
            },
            "players": [
                {
                    "pid": self._pids[p.index],
                    "team": "H" if p.team == Team.HOME else "A",
                    "shirt": p.number,
                    "role": "GK" if p.is_goalkeeper else "",
                }
                for p in self.source.players
            ],
        }

    def frame_messages(self, i: int) -> list[dict[str, Any]]:
        """Tracking message of frame ``i`` followed by the events starting there."""
        f = self.source.frame(i)
        half = f.period
        objs = []
        for k, (x, y) in enumerate(f.positions):
            raw = to_raw(float(x), float(y), half)
            if raw is not None:
                objs.append({"pid": self._pids[k], "x": raw[0], "y": raw[1]})
        braw = to_raw(float(f.ball[0]), float(f.ball[1]), half)
        ts_ms = int(round(f.timestamp * 1000))
        msgs: list[dict[str, Any]] = [
            {
                "type": "tracking",
                "seq": i,
                "ts_ms": ts_ms,
                "half": half,
                "ball": None if braw is None else {"x": braw[0], "y": braw[1]},
                "objs": objs,
            }
        ]
        for e in self._events_by_frame.get(i, []):
            raw = to_raw(e.x, e.y, half) if e.x is not None and e.y is not None else None
            pid = None
            if e.player_id is not None:
                pid = next(
                    (
                        self._pids[p.index]
                        for p in self.source.players
                        if p.player_id == e.player_id
                    ),
                    None,
                )
            msgs.append(
                {
                    "type": "event",
                    "seq": i,
                    "ts_ms": ts_ms,
                    "kind": e.event_type,
                    "detail": e.subtype,
                    "team": None if e.team is None else ("H" if e.team == Team.HOME else "A"),
                    "pid": pid,
                    "x": None if raw is None else raw[0],
                    "y": None if raw is None else raw[1],
                }
            )
        return msgs

    # ------------------------------------------------------------------ server
    def app(self) -> FastAPI:
        app = FastAPI(title="Fake tracking provider")

        @app.get("/status")
        def status() -> dict[str, Any]:
            return {"live_frame": self.live_frame(), "n_frames": len(self.source)}

        @app.websocket("/feed")
        async def feed(ws: WebSocket) -> None:
            await ws.accept()
            rng = random.Random(self.imp.seed + int(self._clock() * 1000))
            await ws.send_json(self.lineup_message())
            nxt = self.live_frame()
            connected_at = self._clock()
            held: list[dict[str, Any]] = []
            try:
                while True:
                    target = self.live_frame()
                    out: list[dict[str, Any]] = []
                    while nxt <= target:
                        out.extend(self.frame_messages(nxt))
                        nxt += 1
                    for msg in impair(out, rng, self.imp, held):
                        await ws.send_json(msg)
                    if (
                        self.imp.disconnect_every_s
                        and self._clock() - connected_at > self.imp.disconnect_every_s
                    ):
                        await ws.close(code=1012)  # "service restart"
                        return
                    if nxt >= len(self.source):
                        await ws.send_json({"type": "end"})
                        await asyncio.sleep(3600)
                    await asyncio.sleep(0.02)
            except (WebSocketDisconnect, RuntimeError):
                return

        return app


def impair(
    msgs: Iterable[dict[str, Any]],
    rng: random.Random,
    imp: Impairments,
    held: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply loss and re-ordering to a batch of messages.

    ``held`` carries packets delayed from the previous batch (out-of-order).
    Events are never dropped (providers usually deliver them reliably).
    """
    out: list[dict[str, Any]] = []
    for m in msgs:
        if m["type"] == "tracking" and rng.random() < imp.drop_prob:
            continue
        if m["type"] == "tracking" and rng.random() < imp.reorder_prob:
            held.append(m)  # will arrive after newer packets
            continue
        out.append(m)
        if held and rng.random() < 0.5:
            out.extend(held)
            held.clear()
    return out
