"""Find the frame where the ball actually crosses the goal line after a goal-scoring shot.

Event providers often time-stamp a goal at the moment of the SHOT. For a live
broadcast feel, score and goal banner should change when the ball goes in.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from livematch.schema import PITCH_LENGTH, PITCH_WIDTH, Event, Team

GOAL_HALF_WIDTH = 7.32 / 2
LINE_TOLERANCE = 0.5  # metres: tracking of the ball is noisy close to the net
POST_TOLERANCE = 1.0  # metres outside the posts still accepted
SEARCH_WINDOW_S = 5.0


def goal_crossing_frame(
    ball: np.ndarray, shot_frame: int, attacks_right: bool, fps: float
) -> int | None:
    """First frame within ``SEARCH_WINDOW_S`` after the shot with the ball over the line.

    Returns ``None`` when the ball is not tracked across the line (fallback:
    the caller keeps the shot frame).
    """
    stop = min(len(ball), shot_frame + int(SEARCH_WINDOW_S * fps) + 1)
    seg = ball[shot_frame:stop]
    if len(seg) == 0:
        return None
    x, y = seg[:, 0], seg[:, 1]
    with np.errstate(invalid="ignore"):
        over = x >= PITCH_LENGTH - LINE_TOLERANCE if attacks_right else x <= LINE_TOLERANCE
        mouth = np.abs(y - PITCH_WIDTH / 2) <= GOAL_HALF_WIDTH + POST_TOLERANCE
    hits = np.flatnonzero(over & mouth)
    return int(shot_frame + hits[0]) if len(hits) else None


def annotate_goal_frames(events: list[Event], ball: np.ndarray, fps: float) -> list[Event]:
    """Return events where every goal carries ``goal_frame`` (crossing frame or shot frame)."""
    out = []
    for e in events:
        if e.is_goal and e.team is not None:
            gf = goal_crossing_frame(ball, e.frame_id, e.team == Team.HOME, fps)
            e = replace(e, goal_frame=gf if gf is not None else e.frame_id)
        out.append(e)
    return out
