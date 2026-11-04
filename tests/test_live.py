"""Live feed: jitter buffer, live clock, fake provider -> adapter -> metrics."""

import random
import socket
import threading
import time

import numpy as np
import pytest

from livematch.live.provider import FakeProvider, Impairments, impair, to_raw
from livematch.metrics.engine import MetricsEngine
from livematch.replay import LiveClock
from livematch.session import MatchSession
from livematch.sources.live_stub import JitterBuffer, ProviderFeedSource
from livematch.sources.metrica import load_metrica

from .conftest import SAMPLE_DIR
from .test_replay import FakeClock


@pytest.fixture(scope="module")
def recording():
    return load_metrica(SAMPLE_DIR / "Sample_Game_1", "rec")


# ------------------------------------------------------------------ jitter buffer
def test_jitter_buffer_reorders_and_fills_gaps():
    jb = JitterBuffer(max_wait=3)
    out = []
    for seq in [10, 12, 11, 13, 15, 16, 17, 18, 9]:
        jb.push(seq, f"p{seq}")
        out.extend(jb.pop_ready())
    assert [s for s, _ in out] == [10, 11, 12, 13, 14, 15, 16, 17, 18]
    assert dict(out)[14] is None  # 14 never arrived -> declared lost
    assert jb.lost == 1 and jb.late == 1 and jb.out_of_order == 1


def test_jitter_buffer_waits_before_declaring_loss():
    jb = JitterBuffer(max_wait=5)
    jb.push(0, "a")
    assert jb.pop_ready() == [(0, "a")]
    jb.push(2, "c")
    assert jb.pop_ready() == []  # 1 may still arrive
    jb.push(1, "b")
    assert jb.pop_ready() == [(1, "b"), (2, "c")]


# ------------------------------------------------------------------ live clock
def test_live_clock_follows_edge_and_dvr():
    clk = FakeClock()
    avail = {"n": 100}
    lc = LiveClock(lambda: avail["n"], 25, clock=clk)
    assert lc.is_live and lc.frame_index() == 99
    avail["n"] = 150
    assert lc.frame_index() == 149
    lc.pause()  # -> DVR, frozen
    avail["n"] = 200
    assert not lc.is_live and lc.frame_index() == 149 and lc.lag_frames() == 50
    lc.play()
    clk.advance(1.0)  # +25 frames at 1x, still 25 behind
    assert lc.frame_index() == 174 and not lc.is_live
    lc.set_speed(5.0)
    clk.advance(1.0)  # would overtake: snaps back to live
    assert lc.is_live and lc.frame_index() == 199
    lc.seek(50)
    assert not lc.is_live and lc.frame_index() == 50
    lc.go_live()
    assert lc.is_live and lc.lag_frames() == 0
    lc.set_speed(10.0)  # faster than live is meaningless at the edge
    assert lc.is_live and lc.speed == 1.0


# ------------------------------------------------------------------ provider format
def test_provider_format_is_foreign(recording):
    prov = FakeProvider(recording)
    lineup = prov.lineup_message()
    assert all(p["pid"].startswith("pl_") for p in lineup["players"])
    msg = prov.frame_messages(2400)[0]  # second half
    assert msg["half"] == 2 and isinstance(msg["ts_ms"], int)
    assert all(-0.1 <= o["x"] <= 1.1 and "pid" in o for o in msg["objs"])
    # second half is sent in stadium orientation (rotated back)
    assert to_raw(10.0, 34.0, 2) == pytest.approx((1 - 10 / 105, 0.5), abs=1e-4)


def _feed(recording, start=0, drop=0.0, reorder=0.0, seed=3):
    prov = FakeProvider(recording, impairments=Impairments(drop_prob=drop, reorder_prob=reorder))
    src = ProviderFeedSource("ws://unused")
    src.ingest(prov.lineup_message())
    rng = random.Random(seed)
    held: list = []
    for i in range(start, len(recording)):
        for m in impair(prov.frame_messages(i), rng, prov.imp, held):
            src.ingest(m)
    for m in held:
        src.ingest(m)
    # flush the tail of the jitter buffer (end of stream)
    src.jitter.max_wait = 0
    src._release()
    return src


def test_adapter_reconstructs_the_match_exactly(recording):
    src = _feed(recording)
    assert len(src) == len(recording)
    assert src.info.period_starts == recording.info.period_starts
    np.testing.assert_allclose(src.positions_array(), recording.positions, atol=1e-3)
    np.testing.assert_allclose(src.ball_array(), recording.ball, atol=1e-3)
    goals = [e for e in src.events if e.is_goal]
    ref = [e for e in recording.events if e.is_goal]
    assert [(g.frame_id, g.goal_frame) for g in goals] == [(g.frame_id, g.goal_frame) for g in ref]
    assert len(src.events) == len(recording.events)


def test_adapter_joining_mid_half_while_home_attacks(recording):
    # minute 01:12: home team camped in the away half; orientation must still be right
    start = 1800
    src = _feed(recording, start=start)
    np.testing.assert_allclose(src.positions_array(), recording.positions[start:], atol=1e-3)


def test_metrics_stay_consistent_with_loss_and_reordering(recording):
    src = _feed(recording, drop=0.02, reorder=0.05)
    assert len(src) == len(recording)  # losses became NaN frames, timeline intact
    st = src.status()
    assert st["lost"] > 0 and st["out_of_order"] > 0
    live = MetricsEngine.for_source(src)
    for f in src.frames():
        live.update(f)
    ref = MetricsEngine.for_source(recording)
    for f in recording.frames():
        ref.update(f)
    a, b = live.snapshot(), ref.snapshot()
    da = {r[0]: r[1] for r in a["players"]}
    db = {r[0]: r[1] for r in b["players"]}
    for i, d in db.items():
        if d > 50:
            # a lost frame removes the two adjacent steps from the distance
            assert da[i] == pytest.approx(d, rel=0.06)
    assert a["poss"]["home"] == pytest.approx(b["poss"]["home"], abs=0.03)
    assert a["teams"]["home"]["goals"] == b["teams"]["home"]["goals"] == 1


def test_session_on_live_source_streams_new_events(recording):
    src = ProviderFeedSource("ws://unused")
    prov = FakeProvider(recording)
    src.ingest(prov.lineup_message())
    for i in range(0, 300):
        for m in prov.frame_messages(i):
            src.ingest(m)
    s = MatchSession(src, MetricsEngine.for_source, clock=FakeClock())
    init = s.init_message()
    assert init["live"] is True
    n0 = len(init["events"])
    for i in range(300, 900):
        for m in prov.frame_messages(i):
            src.ingest(m)
    msg = s.tick(budget_s=5.0)
    assert msg["live"] and msg["at_edge"] and msg["lag"] == 0
    assert msg["f"] == len(src) - 1 == msg["n"] - 1
    assert len(msg.get("ev", [])) == len(src.events) - n0 > 0
    s.handle({"cmd": "pause"})
    assert s.tick()["at_edge"] is False
    s.handle({"cmd": "go_live"})
    assert s.tick()["at_edge"] is True


# ------------------------------------------------------------------ real websocket
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_end_to_end_over_websocket_with_disconnections(recording):
    import uvicorn

    port = _free_port()
    prov = FakeProvider(
        recording,
        speed=4.0,
        impairments=Impairments(drop_prob=0.02, reorder_prob=0.05, disconnect_every_s=1.0),
    )
    server = uvicorn.Server(uvicorn.Config(prov.app(), port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.02)
    src = ProviderFeedSource(f"ws://127.0.0.1:{port}/feed")
    try:
        src.connect()
        assert src.wait_ready(10)
        deadline = time.time() + 15
        while time.time() < deadline and (src.reconnects < 2 or len(src) < 600):
            time.sleep(0.1)
        assert src.reconnects >= 2
        assert len(src) >= 600
        pos = src.positions_array()
        valid = np.isfinite(pos[..., 0])
        assert valid.any(axis=1).mean() > 0.8  # most frames carry players
        # every received frame matches the recording at the same provider sequence
        first = src._first_seq
        k = int(np.flatnonzero(valid.any(axis=1))[-1])
        np.testing.assert_allclose(pos[k], recording.positions[first + k], atol=1e-3)
    finally:
        src.close()
        server.should_exit = True
