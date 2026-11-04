import numpy as np

from livematch.goals import annotate_goal_frames, goal_crossing_frame
from livematch.metrics.events import EventTracker
from livematch.schema import Event, Team

from .conftest import SAMPLE_DIR

FPS = 25.0


def _ball_shot(n=200, start=50, speed=20.0, to_right=True, y=34.0):
    ball = np.full((n, 2), np.nan)
    for k in range(start, n):
        x = 90 + speed * (k - start) / FPS if to_right else 15 - speed * (k - start) / FPS
        ball[k] = (x, y)
    return ball


def test_crossing_frame_home_and_away():
    # 15 m to the line at 20 m/s -> 0.75 s ≈ 18-19 frames (0.5 m tolerance)
    assert goal_crossing_frame(_ball_shot(), 50, True, FPS) == 50 + 19
    away = _ball_shot(to_right=False)
    assert goal_crossing_frame(away, 50, False, FPS) == 50 + 19


def test_crossing_outside_the_posts_is_not_a_goal():
    assert goal_crossing_frame(_ball_shot(y=50.0), 50, True, FPS) is None


def test_untracked_ball_falls_back_to_shot_frame():
    ev = [Event("SHOT", "ON TARGET-GOAL", Team.HOME, "H9", 1, 2.0, 50)]
    ball = np.full((200, 2), np.nan)
    out = annotate_goal_frames(ev, ball, FPS)
    assert out[0].goal_frame == 50
    out2 = annotate_goal_frames(ev, _ball_shot(), FPS)
    assert out2[0].goal_frame == 69 and out2[0].effective_frame == 69


def test_score_changes_when_ball_crosses_line():
    ev = annotate_goal_frames(
        [Event("SHOT", "ON TARGET-GOAL", Team.HOME, "H9", 1, 2.0, 50)], _ball_shot(), FPS
    )
    t = EventTracker(ev)
    t.update(50)
    assert t.counts["home"]["shots"] == 1 and t.counts["home"]["goals"] == 0
    t.update(68)
    assert t.counts["home"]["goals"] == 0
    t.update(69)
    assert t.counts["home"]["goals"] == 1


def test_real_sample_goal_detected():
    from livematch.sources.metrica import load_metrica

    src = load_metrica(SAMPLE_DIR / "Sample_Game_1", "s")
    goals = [e for e in src.events if e.is_goal]
    assert len(goals) == 1  # Game 1, 01:31, home
    g = goals[0]
    assert g.frame_id < g.goal_frame <= g.frame_id + 125
    assert src.ball[g.goal_frame, 0] >= 104.5
