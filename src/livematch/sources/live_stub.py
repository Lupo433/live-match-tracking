"""Skeleton adapter for a REAL live tracking feed.

This module shows where a live provider (e.g. a stadium optical-tracking
system or a commercial feed delivering ~25 Hz positions over WebSocket/TCP)
plugs into the system. Everything downstream (replay, metrics, API, web
client) only depends on :class:`~livematch.sources.base.DataSource`, so a
live feed needs nothing else than a class like this one.

What is already implemented here
--------------------------------
* A thread-safe, append-only in-memory buffer of frames and events
  (:meth:`LiveFeedSource.push_frame`, :meth:`LiveFeedSource.push_event`),
  exposed through the ``DataSource`` interface (``frame(i)``, ``len()``,
  ``events``). ``info.n_frames`` grows as frames arrive.

What you have to implement to connect a provider
------------------------------------------------
1. :meth:`LiveFeedSource.connect` - open the provider connection (auth with an
   API key read from an environment variable, never hard-coded) and start a
   background task/thread that reads messages and calls :meth:`ingest`.
2. :meth:`LiveFeedSource.parse_message` - translate one provider message into
   our schema:

   * map provider player ids to the roster built from the line-ups
     (``Player.index`` must stay stable for the whole match);
   * convert coordinates to metres on a 105 x 68 pitch, origin bottom-left,
     y upwards (providers often use centre-origin or cm units);
   * normalise the attacking direction: the home team must attack towards
     x = 105 in every period (rotate by 180 degrees when it does not, deciding
     once at the start of each period);
   * fill missing players / ball with NaN rather than dropping them;
   * timestamps in seconds since kick-off, ``frame_id`` contiguous from 0.

3. Late / out-of-order packets: buffer a few frames (jitter buffer) and
   re-order by provider timestamp before calling :meth:`push_frame`.
4. Replay side: for a live feed the client should follow the "live edge"
   (latest frame) at 1x; :class:`~livematch.replay.ReplayClock` must have its
   ``n_frames`` refreshed from ``len(source)`` on every tick (or a small
   ``LiveClock`` written that always returns ``len(source) - 1 - delay``).
   Seeking backwards (DVR) works unchanged thanks to random access.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any

import numpy as np

from livematch.goals import SEARCH_WINDOW_S, goal_crossing_frame
from livematch.schema import (
    DEFAULT_FPS,
    PITCH_LENGTH,
    PITCH_WIDTH,
    Event,
    Frame,
    MatchInfo,
    Player,
    Team,
)
from livematch.sources.base import DataSource


class LiveFeedSource(DataSource):
    """A growing DataSource fed by a live provider (connection left to implement)."""

    def __init__(
        self,
        match_id: str,
        players: list[Player],
        fps: float = DEFAULT_FPS,
        title: str = "Live match",
        home_name: str = "Home",
        away_name: str = "Away",
    ) -> None:
        self._players = players
        self._frames: list[Frame] = []
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._info = MatchInfo(
            match_id=match_id,
            title=title,
            home_name=home_name,
            away_name=away_name,
            fps=fps,
            n_frames=0,
            duration_s=0.0,
            period_starts={},
            source="live",
        )

    # ------------------------------------------------------------------ DataSource
    @property
    def info(self) -> MatchInfo:
        with self._lock:
            return self._info

    @property
    def players(self) -> list[Player]:
        return self._players

    @property
    def events(self) -> list[Event]:
        return self._events  # shared, append-only

    def frame(self, frame_id: int) -> Frame:
        with self._lock:
            return self._frames[frame_id]

    # ------------------------------------------------------------------ ingestion
    def push_frame(self, frame: Frame) -> None:
        """Append a frame already converted to the internal schema."""
        if frame.positions.shape != (len(self._players), 2):
            raise ValueError("positions must be aligned to the roster")
        with self._lock:
            expected = len(self._frames)
            if frame.frame_id != expected:
                raise ValueError(f"frame_id must be contiguous (expected {expected})")
            self._frames.append(frame)
            starts = dict(self._info.period_starts)
            starts.setdefault(frame.period, frame.frame_id)
            n = len(self._frames)
            self._info = replace(
                self._info, n_frames=n, duration_s=n / self._info.fps, period_starts=starts
            )

    def positions_array(self) -> np.ndarray:
        """(n_frames, n_players, 2) copy of all positions received so far."""
        with self._lock:
            return (
                np.stack([f.positions for f in self._frames])
                if self._frames
                else np.empty((0, len(self._players), 2))
            )

    def ball_array(self) -> np.ndarray:
        with self._lock:
            return np.stack([f.ball for f in self._frames]) if self._frames else np.empty((0, 2))

    def push_event(self, event: Event) -> None:
        """Append an event. The list is append-only so that consumers holding a
        reference to :attr:`events` (e.g. the metrics engine) see new items."""
        with self._lock:
            self._events.append(event)

    def ingest(self, message: Any) -> None:
        """Parse a raw provider message and push the resulting frame/events."""
        frame, events = self.parse_message(message)
        if frame is not None:
            self.push_frame(frame)
        for e in events:
            self.push_event(e)

    # ------------------------------------------------------------------ to implement
    def connect(self) -> None:  # pragma: no cover - provider specific
        """Open the provider connection and start feeding :meth:`ingest`."""
        raise NotImplementedError(
            "Implement the provider connection here (see the module docstring)."
        )

    def parse_message(self, message: Any) -> tuple[Frame | None, list[Event]]:
        """Translate one provider message into (frame, events).

        The default implementation accepts an already-normalised dict, which is
        handy for tests and for bridging from another process::

            {"frame_id": 0, "t": 0.04, "period": 1,
             "players": [[x, y] | None, ...], "ball": [x, y] | None,
             "events": []}
        """
        players = np.array(
            [p if p is not None else (np.nan, np.nan) for p in message["players"]], dtype=float
        )
        ball = message.get("ball")
        frame = Frame(
            frame_id=int(message["frame_id"]),
            timestamp=float(message["t"]),
            period=int(message["period"]),
            positions=players,
            ball=np.array(ball if ball is not None else (np.nan, np.nan), dtype=float),
        )
        return frame, []


# ---------------------------------------------------------------------------
# Working adapter for the fake provider (livematch.live.provider)
# ---------------------------------------------------------------------------


def _mean_x(pos: np.ndarray, idx: list[int]) -> float:
    """Mean x of the given rows ignoring NaN (NaN when none is valid)."""
    xs = pos[idx, 0] if idx else np.array([])
    xs = xs[np.isfinite(xs)]
    return float(xs.mean()) if len(xs) else float("nan")


class JitterBuffer:
    """Re-orders packets by sequence number and turns gaps into explicit losses.

    Packets are released strictly in sequence order. A missing sequence number
    is declared lost once a packet ``max_wait`` sequence numbers newer has
    arrived (at 25 Hz the default 8 frames = 320 ms of extra latency at most).
    Packets older than the release point are discarded as late.
    """

    def __init__(self, max_wait: int = 8) -> None:
        self.max_wait = max_wait
        self._items: dict[int, Any] = {}
        self.next_seq: int | None = None
        self.received = 0
        self.late = 0
        self.out_of_order = 0
        self.lost = 0
        self._max_seen = -1

    def push(self, seq: int, item: Any) -> None:
        self.received += 1
        if self.next_seq is None:
            self.next_seq = seq
        if seq < self.next_seq or seq in self._items:
            self.late += 1
            return
        if seq < self._max_seen:
            self.out_of_order += 1
        self._max_seen = max(self._max_seen, seq)
        self._items[seq] = item

    def pop_ready(self) -> list[tuple[int, Any]]:
        """Release what can be released: ``(seq, item)``, ``item is None`` for a lost packet."""
        out: list[tuple[int, Any]] = []
        if self.next_seq is None:
            return out
        while True:
            if self.next_seq in self._items:
                out.append((self.next_seq, self._items.pop(self.next_seq)))
                self.next_seq += 1
            elif self._items and max(self._items) - self.next_seq >= self.max_wait:
                out.append((self.next_seq, None))
                self.lost += 1
                self.next_seq += 1
            else:
                return out

    def stats(self) -> dict[str, int]:
        return {
            "received": self.received,
            "late": self.late,
            "out_of_order": self.out_of_order,
            "lost": self.lost,
        }


class ProviderFeedSource(LiveFeedSource):
    """Adapter for the fake provider protocol (see :mod:`livematch.live.provider`).

    * ``lineup``  -> roster (provider ids mapped to stable roster indices)
    * ``tracking`` -> metres, attacking direction normalised per half, NaN for
      players not listed, through a :class:`JitterBuffer` (losses become NaN frames)
    * ``event``   -> :class:`Event`; goals are held until the ball crosses the
      goal line (or 5 s pass) so that ``goal_frame`` is known.
    """

    def __init__(
        self, url: str, match_id: str = "live_demo", title: str = "Live demo", max_wait: int = 8
    ) -> None:
        super().__init__(match_id, [], title=title)
        self.url = url
        self.jitter = JitterBuffer(max_wait)
        self.reconnects = 0
        self.unknown_ids = 0
        self.ended = False
        self._pid_index: dict[str, int] = {}
        self._first_seq: int | None = None
        self._flip: dict[int, bool] = {}
        self._last: tuple[float, int] = (0.0, 1)  # (timestamp, period) of the last frame
        self._ball: list[np.ndarray] = []
        self._events_by_seq: dict[int, list[dict[str, Any]]] = {}
        self._pending_goals: list[Event] = []
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ connection
    def connect(self) -> None:
        """Start a background thread that keeps a WebSocket open (auto-reconnect)."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._thread_main, daemon=True, name="feed")
            self._thread.start()

    def close(self) -> None:
        self._stop.set()

    def wait_ready(self, timeout: float = 10.0) -> bool:
        """Block until the line-up has been received."""
        return self._ready.wait(timeout)

    def _thread_main(self) -> None:
        import asyncio

        asyncio.run(self._run())

    async def _run(self) -> None:
        import asyncio
        import json

        import websockets

        backoff = 0.2
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, max_size=None) as ws:
                    backoff = 0.2
                    async for raw in ws:
                        self.ingest(json.loads(raw))
                        if self._stop.is_set():
                            return
            except Exception:  # connection refused / dropped: retry
                pass
            if self._stop.is_set() or self.ended:
                return
            self.reconnects += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 5.0)

    # ------------------------------------------------------------------ parsing
    def ingest(self, message: Any) -> None:
        kind = message.get("type")
        if kind == "lineup":
            self._on_lineup(message)
        elif kind == "tracking" and self._ready.is_set():
            self.jitter.push(int(message["seq"]), self.parse_tracking(message))
            self._release()
        elif kind == "event" and self._ready.is_set():
            seq = int(message["seq"])
            nxt = self.jitter.next_seq
            if nxt is not None and seq < nxt:
                self._emit_event(message)  # its frame is already out
            else:
                self._events_by_seq.setdefault(seq, []).append(message)
        elif kind == "end":
            self.ended = True

    def _on_lineup(self, msg: dict[str, Any]) -> None:
        if self._ready.is_set():
            return  # reconnection: keep the roster we already have
        players = []
        for i, p in enumerate(msg["players"]):
            team = Team.HOME if p["team"] == "H" else Team.AWAY
            players.append(
                Player(
                    index=i,
                    player_id=f"{team.value[0].upper()}{p['shirt']}",
                    team=team,
                    number=int(p["shirt"]),
                    name=p["pid"],
                    is_goalkeeper=p.get("role") == "GK",
                )
            )
            self._pid_index[p["pid"]] = i
        self._players = players
        self._info = replace(
            self._info,
            fps=float(msg.get("fps", DEFAULT_FPS)),
            home_name=msg["teams"]["H"]["name"],
            away_name=msg["teams"]["A"]["name"],
        )
        self._ready.set()

    @staticmethod
    def _to_metres(x: float, y: float) -> tuple[float, float]:
        return x * PITCH_LENGTH, (1.0 - y) * PITCH_WIDTH

    def parse_tracking(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Provider tracking message -> metres in stadium orientation (not yet normalised)."""
        pos = np.full((len(self._players), 2), np.nan)
        for o in msg["objs"]:
            idx = self._pid_index.get(o["pid"])
            if idx is None:
                self.unknown_ids += 1
                continue
            pos[idx] = self._to_metres(o["x"], o["y"])
        b = msg.get("ball")
        ball = np.array(self._to_metres(b["x"], b["y"]) if b else (np.nan, np.nan))
        return {"t": msg["ts_ms"] / 1000.0, "half": int(msg["half"]), "pos": pos, "ball": ball}

    def _needs_flip(self, half: int, pos: np.ndarray) -> bool:
        """Decided once per half, from the first frame received in that half.

        The two goalkeepers are the most reliable cue (we may join mid-half,
        while the home team is attacking deep); without them, compare the mean
        x of the two teams. Home must end up attacking towards x = 105.
        """
        if half not in self._flip:
            home = [p.index for p in self._players if p.team == Team.HOME]
            away = [p.index for p in self._players if p.team == Team.AWAY]
            gk_h = [p.index for p in self._players if p.team == Team.HOME and p.is_goalkeeper]
            gk_a = [p.index for p in self._players if p.team == Team.AWAY and p.is_goalkeeper]
            hx, ax = _mean_x(pos, gk_h), _mean_x(pos, gk_a)
            if not (np.isfinite(hx) and np.isfinite(ax)):
                hx, ax = _mean_x(pos, home), _mean_x(pos, away)
            self._flip[half] = bool(np.isfinite(hx) and np.isfinite(ax) and hx > ax)
        return self._flip[half]

    def _flip_xy(self, xy: np.ndarray) -> np.ndarray:
        out = xy.copy()
        out[..., 0] = PITCH_LENGTH - out[..., 0]
        out[..., 1] = PITCH_WIDTH - out[..., 1]
        return out

    def _release(self) -> None:
        fps = self._info.fps
        for seq, item in self.jitter.pop_ready():
            if self._first_seq is None:
                self._first_seq = seq
            fid = seq - self._first_seq
            if item is None:  # lost packet: explicit NaN frame keeps the timeline regular
                t, half = self._last[0] + 1.0 / fps, self._last[1]
                pos = np.full((len(self._players), 2), np.nan)
                ball = np.array([np.nan, np.nan])
            else:
                t, half, pos, ball = item["t"], item["half"], item["pos"], item["ball"]
                if self._needs_flip(half, pos):
                    pos, ball = self._flip_xy(pos), self._flip_xy(ball)
            self._last = (t, half)
            self.push_frame(Frame(fid, t, half, pos, ball))
            self._ball.append(ball)
            for m in self._events_by_seq.pop(seq, []):
                self._emit_event(m)
            self._check_goals()

    def _emit_event(self, m: dict[str, Any]) -> None:
        if self._first_seq is None:
            return
        team = None if m.get("team") is None else (Team.HOME if m["team"] == "H" else Team.AWAY)
        half = self._last[1]
        x = y = None
        if m.get("x") is not None and m.get("y") is not None:
            xy = np.array(self._to_metres(m["x"], m["y"]))
            if self._flip.get(half, False):
                xy = self._flip_xy(xy)
            x, y = float(xy[0]), float(xy[1])
        idx = self._pid_index.get(m.get("pid") or "")
        ev = Event(
            event_type=str(m["kind"]),
            subtype=str(m.get("detail") or ""),
            team=team,
            player_id=None if idx is None else self._players[idx].player_id,
            period=half,
            timestamp=m["ts_ms"] / 1000.0,
            frame_id=max(0, int(m["seq"]) - self._first_seq),
            x=x,
            y=y,
        )
        if ev.is_goal and ev.team is not None:
            self._pending_goals.append(ev)
        else:
            self.push_event(ev)

    def _check_goals(self) -> None:
        if not self._pending_goals:
            return
        n = len(self._ball)
        fps = self._info.fps
        still = []
        for g in self._pending_goals:
            seg = np.array(self._ball[g.frame_id : n])
            gf = goal_crossing_frame(seg, 0, g.team == Team.HOME, fps) if len(seg) else None
            if gf is not None:
                self.push_event(replace(g, goal_frame=g.frame_id + gf))
            elif n - g.frame_id > int(SEARCH_WINDOW_S * fps):
                self.push_event(replace(g, goal_frame=g.frame_id))  # ball not tracked: fallback
            else:
                still.append(g)
        self._pending_goals = still

    def status(self) -> dict[str, Any]:
        return {
            **self.jitter.stats(),
            "reconnects": self.reconnects,
            "unknown_ids": self.unknown_ids,
            "frames": len(self),
        }
