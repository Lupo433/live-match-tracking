"""Metric components on synthetic inputs with a known answer."""

import numpy as np
import pytest

from livematch.metrics.engine import MetricsEngine
from livematch.metrics.events import EventTracker
from livematch.metrics.heatmap import Heatmaps
from livematch.metrics.kinematics import EffortTracker, Kinematics, PointKinematics
from livematch.metrics.pitch_control import PitchControl
from livematch.metrics.possession import Possession
from livematch.metrics.shape import team_shape
from livematch.schema import Event, Frame, Player, Team

FPS = 25.0


def run_track(speed_profile: list[tuple[float, float]], y: float = 34.0):
    """Feed a single player moving along x with (speed m/s, duration s) segments."""
    kin = Kinematics(1, FPS)
    spr = EffortTracker(1, FPS, 7.0)
    hi = EffortTracker(1, FPS, 5.5)
    x = 10.0
    kin.update(np.array([[x, y]]), 1)
    for v, dur in speed_profile:
        for _ in range(int(round(dur * FPS))):
            x += v / FPS
            kin.update(np.array([[x, y]]), 1)
            spr.update(kin.speed, kin.centre_step)
            hi.update(kin.speed, kin.centre_step)
    return kin, spr, hi


def test_straight_line_distance_and_speed():
    kin, spr, hi = run_track([(5.0, 10.0)])
    assert kin.distance[0] == pytest.approx(50.0, abs=1e-9)
    assert kin.speed[0] == pytest.approx(5.0, abs=1e-6)
    assert kin.max_speed_reached[0] == pytest.approx(5.0, abs=1e-6)
    assert spr.count[0] == 0 and hi.count[0] == 0


def test_sprint_detected_with_distance():
    kin, spr, hi = run_track([(0.0, 2.0), (8.0, 3.0), (0.0, 2.0)])
    assert kin.distance[0] == pytest.approx(24.0, abs=1e-9)
    assert spr.count[0] == 1
    assert 20.0 <= spr.distance[0] <= 24.0
    assert hi.count[0] == 1
    assert spr.distance[0] <= hi.distance[0] <= 24.0
    assert kin.max_speed_reached[0] == pytest.approx(8.0, abs=1e-6)


def test_short_burst_is_not_a_sprint():
    _, spr, hi = run_track([(0.0, 2.0), (8.0, 0.6), (0.0, 2.0)])
    assert spr.count[0] == 0 and hi.count[0] == 0
    assert spr.distance[0] == 0


def test_high_intensity_but_not_sprint():
    _, spr, hi = run_track([(0.0, 1.0), (6.0, 4.0), (0.0, 1.0)])
    assert spr.count[0] == 0
    assert hi.count[0] == 1
    assert hi.distance[0] == pytest.approx(24.0, abs=2.5)


def test_two_separate_sprints():
    _, spr, _ = run_track([(0.0, 1.0), (8.0, 2.0), (2.0, 2.0), (8.0, 2.0), (0.0, 1.0)])
    assert spr.count[0] == 2


def test_gaps_and_jumps_are_not_distance():
    kin = Kinematics(1, FPS)
    kin.update(np.array([[0.0, 0.0]]), 1)
    kin.update(np.array([[np.nan, np.nan]]), 1)  # player leaves
    kin.update(np.array([[50.0, 0.0]]), 1)  # re-appears far away
    kin.update(np.array([[90.0, 0.0]]), 1)  # glitch: 40 m in one frame
    assert kin.distance[0] == 0.0
    kin.update(np.array([[90.2, 0.0]]), 2)  # new period resets the track
    assert kin.distance[0] == 0.0


def test_ball_speed():
    b = PointKinematics(FPS)
    for k in range(50):
        b.update(10 + 20.0 * k / FPS, 30.0, 1)
    assert b.speed == pytest.approx(20.0, abs=1e-6)
    b.update(float("nan"), float("nan"), 1)
    assert b.speed == 0.0


def test_heatmap_accumulates_seconds():
    h = Heatmaps(2, FPS, nx=21, ny=14)
    for _ in range(250):
        h.update(np.array([[2.0, 2.0], [np.nan, np.nan]]))
    assert h.seconds(0)[0, 0] == pytest.approx(10.0)
    assert h.seconds(0).sum() == pytest.approx(10.0)
    assert h.seconds(1).sum() == 0
    h.update(np.array([[104.9, 67.9], [52.6, 34.1]]))
    assert h.seconds(0)[13, 20] == pytest.approx(0.04)
    assert h.seconds(1)[7, 10] == pytest.approx(0.04)


def test_possession_shares():
    teams = np.array([0, 1])
    p = Possession(teams, radius=3.0)
    home_ball = np.array([[10.0, 10.0], [60.0, 30.0]])
    for _ in range(100):  # ball at the home player's feet
        p.update(home_ball, np.array([10.5, 10.0]))
    for _ in range(50):  # loose ball, nobody close: stays with home
        p.update(home_ball, np.array([35.0, 20.0]))
    for _ in range(150):  # away player has the ball
        p.update(home_ball, np.array([60.0, 31.0]))
    for _ in range(500):  # dead ball: ignored
        p.update(home_ball, np.array([np.nan, np.nan]))
    assert p.share() == pytest.approx((0.5, 0.5))
    assert p.current_player is None


def test_team_shape_values():
    xy = np.array([[10.0, 10.0], [20.0, 50.0], [30.0, 30.0], [40.0, 20.0], [50.0, 40.0]])
    s = team_shape(xy, attacks_right=True)
    assert s.cx == pytest.approx(30.0) and s.cy == pytest.approx(30.0)
    assert s.width == pytest.approx(40.0) and s.length == pytest.approx(40.0)
    assert s.line == pytest.approx(25.0)  # mean of the 4 deepest x: 10, 20, 30, 40
    s_away = team_shape(xy, attacks_right=False)
    assert s_away.line == pytest.approx(105 - 35.0)  # deepest from x = 105: 50, 40, 30, 20


def test_pitch_control_symmetric_and_dominant():
    teams = np.array([0, 1])
    pc = PitchControl(teams)
    sym = np.array([[30.0, 34.0], [75.0, 34.0]])
    grid = pc.compute(sym, np.zeros((2, 2)))
    assert grid.mean() == pytest.approx(0.5, abs=1e-6)
    # cells near the home player belong to home
    assert grid.reshape(pc.ny, pc.nx)[10, 9] > 0.95
    teams3 = np.array([0, 0, 0, 1])
    pc3 = PitchControl(teams3)
    xy = np.array([[20.0, 20.0], [50.0, 50.0], [80.0, 20.0], [100.0, 65.0]])
    assert pc3.compute(xy, np.zeros((4, 2))).mean() > 0.75


def test_event_tracker_counts():
    ev = [
        Event("SHOT", "ON TARGET-GOAL", Team.HOME, "H9", 1, 10.0, 250),
        Event("SHOT", "OFF TARGET-OUT", Team.AWAY, "A9", 1, 20.0, 500),
        Event("FAULT RECEIVED", "", Team.HOME, "H7", 1, 30.0, 750),
        Event("PASS", "", Team.AWAY, "A4", 1, 31.0, 775),
    ]
    t = EventTracker(ev)
    assert t.update(100) == []
    assert len(t.update(600)) == 2
    assert t.counts["home"]["goals"] == 1 and t.counts["home"]["on_target"] == 1
    assert t.counts["away"]["shots"] == 1 and t.counts["away"]["on_target"] == 0
    t.update(10_000)
    assert t.counts["away"]["fouls"] == 1  # foul received by home = committed by away
    assert t.counts["away"]["passes"] == 1


def _frames_two_players(n: int):
    for k in range(n):
        pos = np.array([[10.0 + 5.0 * k / FPS, 34.0], [90.0, 34.0]])
        yield Frame(k, k / FPS, 1, pos, np.array([pos[0, 0] + 0.5, 34.0]))


def test_engine_end_to_end_known_answer():
    players = [Player(0, "H1", Team.HOME, 9), Player(1, "A1", Team.AWAY, 4)]
    eng = MetricsEngine(players, FPS)
    for f in _frames_two_players(251):  # 10 s at 5 m/s
        eng.update(f)
    snap = eng.snapshot()
    rows = {r[0]: r for r in snap["players"]}
    assert rows[0][1] == pytest.approx(50.0, abs=0.01)
    assert rows[1][1] == 0.0
    assert snap["poss"]["home"] == pytest.approx(1.0)
    assert snap["teams"]["home"]["dist_km"] == pytest.approx(0.05, abs=1e-3)
    assert snap["ball"]["v"] == pytest.approx(5.0, abs=1e-6)
    assert 0 < snap["pc"]["home"] < 1


def test_engine_checkpoint_restore_is_exact(synthetic):
    eng = MetricsEngine.for_source(synthetic)
    for f in synthetic.frames(0, 1000):
        eng.update(f)
    state = eng.checkpoint()
    for f in synthetic.frames(1000, 2000):
        eng.update(f)
    expected = eng.snapshot()
    eng.restore(state)
    for f in synthetic.frames(1000, 2000):
        eng.update(f)
    assert eng.snapshot() == expected
