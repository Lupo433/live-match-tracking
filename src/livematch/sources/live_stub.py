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

from livematch.schema import DEFAULT_FPS, Event, Frame, MatchInfo, Player
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
        with self._lock:
            return list(self._events)

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

    def push_event(self, event: Event) -> None:
        with self._lock:
            self._events.append(event)
            self._events.sort(key=lambda e: e.timestamp)

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
