import numpy as np
import pytest

from livematch.metrics.engine import MetricsEngine
from livematch.sources.base import DataSource
from livematch.sources.live_stub import LiveFeedSource


def test_live_source_grows_and_feeds_the_engine(synthetic):
    live = LiveFeedSource("live-test", synthetic.players, fps=25)
    assert isinstance(live, DataSource)
    assert len(live) == 0
    engine = MetricsEngine.for_source(live)
    for f in synthetic.frames(0, 100):
        live.ingest(
            {
                "frame_id": f.frame_id,
                "t": f.timestamp,
                "period": f.period,
                "players": [None if np.isnan(p[0]) else p.tolist() for p in f.positions],
                "ball": f.ball.tolist(),
            }
        )
        engine.update(live.frame(len(live) - 1))
    assert len(live) == 100
    assert live.info.period_starts == {1: 0}
    ref = MetricsEngine.for_source(synthetic)
    for f in synthetic.frames(0, 100):
        ref.update(f)
    # kinematic columns identical (the live source got no events, so xT differs)
    assert [r[:7] for r in engine.snapshot()["players"]] == [
        r[:7] for r in ref.snapshot()["players"]
    ]


def test_live_source_rejects_gaps(synthetic):
    live = LiveFeedSource("live-test", synthetic.players)
    with pytest.raises(ValueError):
        live.push_frame(synthetic.frame(5))
