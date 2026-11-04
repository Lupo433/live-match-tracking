"""Internal data model shared by every component.

Coordinate system (metres):
    * x in [0, PITCH_LENGTH] along the long side, y in [0, PITCH_WIDTH].
    * Origin at the bottom-left corner when the pitch is drawn with the home
      team attacking left -> right; y grows upwards.
    * The home team ALWAYS attacks towards x = PITCH_LENGTH (both halves).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0
DEFAULT_FPS = 25.0


class Team(StrEnum):
    """Team side."""

    HOME = "home"
    AWAY = "away"


@dataclass(frozen=True, slots=True)
class Player:
    """A roster entry. ``index`` is the column of the player in ``Frame.positions``."""

    index: int
    player_id: str
    team: Team
    number: int
    name: str = ""
    is_goalkeeper: bool = False


@dataclass(frozen=True, slots=True)
class Frame:
    """One tracking sample.

    Attributes:
        frame_id: progressive frame number (0-based, contiguous within a source).
        timestamp: seconds since kick-off of the first half (continuous).
        period: 1 = first half, 2 = second half (3/4 extra time).
        positions: float array of shape (n_players, 2) aligned to the roster;
            NaN rows mean "player not on the pitch / not tracked".
        ball: float array of shape (2,), NaN when the ball is not tracked.
    """

    frame_id: int
    timestamp: float
    period: int
    positions: np.ndarray
    ball: np.ndarray

    @property
    def ball_visible(self) -> bool:
        return bool(np.isfinite(self.ball).all())

    def on_pitch(self) -> np.ndarray:
        """Boolean mask of players with a valid position."""
        return np.isfinite(self.positions).all(axis=1)


@dataclass(frozen=True, slots=True)
class Event:
    """A discrete match event (pass, shot, foul, ...).

    ``x``/``y`` and ``end_x``/``end_y`` use the same metric coordinate system as
    frames (home attacks left -> right). Missing coordinates are ``None``.
    """

    event_type: str
    subtype: str
    team: Team | None
    player_id: str | None
    period: int
    timestamp: float
    frame_id: int
    x: float | None = None
    y: float | None = None
    end_x: float | None = None
    end_y: float | None = None
    end_timestamp: float | None = None
    to_player_id: str | None = None
    """Receiver of a pass (when known)."""
    goal_frame: int | None = None
    """For goals: frame where the ball crosses the line (falls back to ``frame_id``)."""

    @property
    def is_goal(self) -> bool:
        return self.event_type == "SHOT" and "GOAL" in self.subtype.upper()

    @property
    def effective_frame(self) -> int:
        """Frame at which the event "happens" for the live clock (goal line for goals)."""
        return self.goal_frame if self.goal_frame is not None else self.frame_id


@dataclass(frozen=True, slots=True)
class MatchInfo:
    """Static metadata of a match."""

    match_id: str
    title: str
    home_name: str
    away_name: str
    fps: float
    n_frames: int
    duration_s: float
    period_starts: dict[int, int] = field(default_factory=dict)
    """Mapping period -> first frame_id of that period."""
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "title": self.title,
            "home_name": self.home_name,
            "away_name": self.away_name,
            "fps": self.fps,
            "n_frames": self.n_frames,
            "duration_s": self.duration_s,
            "period_starts": {str(k): v for k, v in self.period_starts.items()},
            "source": self.source,
        }


def match_clock(timestamp: float, period: int, period_start_ts: float) -> str:
    """Broadcast-style clock (45:00 offset in the second half)."""
    offset = {1: 0, 2: 45 * 60, 3: 90 * 60, 4: 105 * 60}.get(period, 0)
    secs = max(0.0, timestamp - period_start_ts) + offset
    return f"{int(secs // 60):02d}:{int(secs % 60):02d}"
