import numpy as np
import pytest

from livematch.schema import PITCH_LENGTH, PITCH_WIDTH, Team
from livematch.sources.metrica import _flip, _to_metres, load_metrica

from .conftest import SAMPLE_DIR


@pytest.fixture(scope="module")
def sample():
    return load_metrica(SAMPLE_DIR / "Sample_Game_1", "sample")


def test_to_metres_corners():
    pts = np.array([[0.0, 0.0], [1.0, 1.0], [0.5, 0.5]])
    m = _to_metres(pts)
    # Metrica origin is top-left -> (0, 68) in our bottom-left system
    assert np.allclose(m[0], [0.0, PITCH_WIDTH])
    assert np.allclose(m[1], [PITCH_LENGTH, 0.0])
    assert np.allclose(m[2], [52.5, 34.0])


def test_flip_is_rotation_around_centre():
    pts = np.array([[10.0, 20.0]])
    assert np.allclose(_flip(pts), [[95.0, 48.0]])
    assert np.allclose(_flip(_flip(pts)), pts)


def test_sample_shape_and_metadata(sample):
    assert sample.info.fps == 25.0
    assert len(sample) == 3000
    assert sample.info.period_starts == {1: 0, 2: 1500}
    assert len(sample.players) == 28  # 14 per team including substitutes
    assert sum(p.team == Team.HOME for p in sample.players) == 14


def test_first_frame_conversion(sample):
    f = sample.frame(0)
    gk = sample.players[0]
    assert gk.player_id == "H11" and gk.number == 11 and gk.is_goalkeeper
    # raw: Player11 = (0.00082, 0.48238), first half not flipped
    assert np.allclose(f.positions[0], [0.00082 * 105, (1 - 0.48238) * 68])
    # 22 players on the pitch, substitutes are NaN
    assert f.on_pitch().sum() == 22


def test_home_attacks_right_in_both_halves(sample):
    home = [p.index for p in sample.players if p.team == Team.HOME]
    away = [p.index for p in sample.players if p.team == Team.AWAY]
    for period, start in sample.info.period_starts.items():
        sl = slice(start, start + 250)
        hx = np.nanmean(sample.positions[sl, home, 0])
        ax = np.nanmean(sample.positions[sl, away, 0])
        assert hx < ax, f"period {period}"
        # home goalkeeper close to x = 0
        assert np.nanmean(sample.positions[sl, 0, 0]) < 20


def test_second_half_flipped(sample):
    # raw second half: home GK at x ~0.90 (right side) -> after flip ~10 m
    f = sample.frame(1500)
    assert f.period == 2
    assert f.positions[0, 0] < 15


def test_events_loaded_and_aligned(sample):
    ev = sample.events
    assert len(ev) > 20
    assert ev[0].event_type == "SET PIECE"
    assert all(0 <= e.frame_id < len(sample) for e in ev)
    assert all(ev[i].timestamp <= ev[i + 1].timestamp for i in range(len(ev) - 1))
    passes = [e for e in ev if e.event_type == "PASS" and e.x is not None]
    assert passes and all(0 <= e.x <= 105 and 0 <= e.y <= 68 for e in passes)


def test_ball_nan_handled(sample):
    assert sample.ball.shape == (3000, 2)
    f = sample.frame(0)
    assert f.ball_visible
