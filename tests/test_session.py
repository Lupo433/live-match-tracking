import json

import pytest

from livematch.metrics.engine import MetricsEngine
from livematch.session import CheckpointStore, MatchSession

from .test_replay import FakeClock


def reference_snapshot(source, n_frames):
    eng = MetricsEngine.for_source(source)
    for f in source.frames(0, n_frames):
        eng.update(f)
    return eng.snapshot()


def test_tick_consumes_every_frame_at_10x(synthetic):
    clk = FakeClock()
    s = MatchSession(synthetic, MetricsEngine.for_source, clock=clk)
    s.replay.set_speed(10.0)
    s.replay.play()
    for _ in range(25):  # one second of wall clock at 10x = 250 frames
        clk.advance(0.04)
        msg = s.tick(budget_s=1.0)
    assert msg["f"] == 250
    assert s.cursor == 251  # no frame skipped by the metrics
    json.dumps(msg)  # serialisable (no NaN)


def test_seek_backward_gives_same_stats_as_direct_processing(synthetic):
    clk = FakeClock()
    s = MatchSession(synthetic, MetricsEngine.for_source, clock=clk)
    s.seek(2000)
    s.tick(budget_s=10.0)
    s.seek(700)
    msg = s.tick(budget_s=10.0, force_stats=True)
    assert msg["f"] == 700
    assert msg["st"] == reference_snapshot(synthetic, 701)


def test_seek_forward_uses_shared_checkpoints(synthetic):
    store = CheckpointStore(synthetic, MetricsEngine.for_source, every=500)
    store.run()  # synchronous for the test
    assert store.done and store.best(1234)[0] == 1000
    s = MatchSession(synthetic, MetricsEngine.for_source, clock=FakeClock(), store=store)
    s.seek(2600)
    assert s.cursor == 2500  # jumped straight to the checkpoint
    msg = s.tick(budget_s=10.0, force_stats=True)
    assert msg["st"] == reference_snapshot(synthetic, 2601)


def test_metrics_catch_up_respects_time_budget(synthetic):
    s = MatchSession(synthetic, MetricsEngine.for_source, clock=FakeClock())
    s.seek(2999)
    msg = s.tick(budget_s=0.0)
    assert msg["f"] == 2999
    assert msg["sync"] < 1.0  # still catching up, but the frame was delivered
    for _ in range(200):
        msg = s.tick(budget_s=0.05)
        if msg["sync"] >= 1.0:
            break
    assert msg["sync"] == 1.0


def test_commands(synthetic):
    s = MatchSession(synthetic, MetricsEngine.for_source, clock=FakeClock())
    s.handle({"cmd": "play"})
    assert s.replay.playing
    s.handle({"cmd": "pause"})
    s.handle({"cmd": "seek", "minute": 1})
    assert s.replay.frame_index() == 1500
    s.handle({"cmd": "seek", "fraction": 1.0})
    assert s.replay.frame_index() == len(synthetic) - 1
    s.handle({"cmd": "set_speed", "speed": 5})
    assert s.replay.speed == 5
    s.handle({"cmd": "select_player", "player": 3})
    assert s.tick(force_stats=True)["st"]["heat"]["i"] == 3
    with pytest.raises(ValueError):
        s.handle({"cmd": "explode"})
