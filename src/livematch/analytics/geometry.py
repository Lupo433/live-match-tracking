"""Shared geometry: attacking-direction normalisation, shot distance and angle."""

from __future__ import annotations

import math

from livematch.schema import PITCH_LENGTH, PITCH_WIDTH, Event, Team

GOAL_WIDTH = 7.32


def attacking_xy(x: float, y: float, team: Team | None) -> tuple[float, float]:
    """Coordinates seen by the team in possession, always attacking towards x = 105."""
    if team == Team.AWAY:
        return PITCH_LENGTH - x, PITCH_WIDTH - y
    return x, y


def event_start(e: Event) -> tuple[float, float] | None:
    if e.x is None or e.y is None:
        return None
    return attacking_xy(e.x, e.y, e.team)


def event_end(e: Event) -> tuple[float, float] | None:
    if e.end_x is None or e.end_y is None:
        return None
    return attacking_xy(e.end_x, e.end_y, e.team)


def shot_distance(x: float, y: float) -> float:
    """Distance (m) from the centre of the goal at x = 105."""
    return math.hypot(PITCH_LENGTH - x, y - PITCH_WIDTH / 2)


def shot_angle(x: float, y: float) -> float:
    """Angle (rad) subtended by the goal mouth from (x, y); larger = better view."""
    dx = max(PITCH_LENGTH - x, 1e-6)
    dy = abs(y - PITCH_WIDTH / 2)
    a = math.atan2(GOAL_WIDTH * dx, dx * dx + dy * dy - (GOAL_WIDTH / 2) ** 2)
    return a if a >= 0 else a + math.pi
