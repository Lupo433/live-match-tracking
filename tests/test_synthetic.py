import numpy as np

from livematch.schema import PITCH_LENGTH, PITCH_WIDTH, Team
from livematch.sources.base import DataSource


def test_synthetic_is_a_datasource(synthetic):
    assert isinstance(synthetic, DataSource)
    assert len(synthetic) == 120 * 25
    assert synthetic.info.fps == 25


def test_roster_22_players(synthetic):
    players = synthetic.players
    assert len(players) == 22
    assert all(p.index == i for i, p in enumerate(players))
    assert len(synthetic.team_players(Team.HOME)) == 11
    assert sum(p.is_goalkeeper for p in players) == 2


def test_positions_inside_pitch_and_plausible_speed(synthetic):
    pos = synthetic.positions
    assert np.isfinite(pos).all()
    assert pos[..., 0].min() >= -1.5 and pos[..., 0].max() <= PITCH_LENGTH + 1.5
    assert pos[..., 1].min() >= -1.5 and pos[..., 1].max() <= PITCH_WIDTH + 1.5
    # within each period, no player exceeds ~10 m/s
    p1 = synthetic.info.period_starts[2]
    speeds = np.linalg.norm(np.diff(pos[:p1], axis=0), axis=2) * 25
    assert speeds.max() < 10.5


def test_frames_iteration_and_random_access(synthetic):
    frames = list(synthetic.frames(10, 15))
    assert [f.frame_id for f in frames] == [10, 11, 12, 13, 14]
    f = synthetic.frame(100)
    assert f.positions.shape == (22, 2)
    assert abs(f.timestamp - 4.0) < 1e-9
    assert f.on_pitch().all()


def test_home_attacks_right(synthetic):
    # home goalkeeper stays in the left third throughout
    assert np.nanmean(synthetic.positions[:, 0, 0]) < 20


def test_deterministic():
    from livematch.sources.synthetic import SyntheticSource

    a = SyntheticSource(duration_s=10, seed=5)
    b = SyntheticSource(duration_s=10, seed=5)
    assert np.array_equal(a.positions, b.positions)
