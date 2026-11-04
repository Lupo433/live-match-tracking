import pytest

from livematch.replay import ReplayClock


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.fixture
def clk():
    return FakeClock()


def test_starts_paused_at_zero(clk):
    r = ReplayClock(1000, 25, clock=clk)
    clk.advance(5)
    assert not r.playing
    assert r.frame_index() == 0


def test_realtime_timing(clk):
    r = ReplayClock(10_000, 25, clock=clk)
    r.play()
    clk.advance(2.0)
    assert r.position() == pytest.approx(50.0)


@pytest.mark.parametrize("speed", [1.0, 2.0, 5.0, 10.0])
def test_speed_multiplies_rate(clk, speed):
    r = ReplayClock(100_000, 25, clock=clk)
    r.set_speed(speed)
    r.play()
    clk.advance(4.0)
    assert r.position() == pytest.approx(100 * speed)


def test_speed_change_does_not_jump(clk):
    r = ReplayClock(100_000, 25, clock=clk)
    r.play()
    clk.advance(1.0)  # 25 frames
    r.set_speed(10.0)
    assert r.position() == pytest.approx(25)
    clk.advance(1.0)  # +250
    assert r.position() == pytest.approx(275)


def test_pause_and_resume(clk):
    r = ReplayClock(10_000, 25, clock=clk)
    r.play()
    clk.advance(1.0)
    r.pause()
    clk.advance(10.0)
    assert r.position() == pytest.approx(25)
    r.play()
    clk.advance(1.0)
    assert r.position() == pytest.approx(50)


def test_seek_while_playing_and_paused(clk):
    r = ReplayClock(10_000, 25, clock=clk)
    r.seek(500)
    assert r.frame_index() == 500
    r.play()
    clk.advance(1.0)
    assert r.position() == pytest.approx(525)
    r.seek_seconds(60)  # minute 1
    assert r.position() == pytest.approx(1500)
    clk.advance(0.4)
    assert r.position() == pytest.approx(1510)


def test_seek_is_clamped(clk):
    r = ReplayClock(100, 25, clock=clk)
    r.seek(-10)
    assert r.position() == 0
    r.seek(10_000)
    assert r.position() == 99


def test_stops_at_end_and_restarts(clk):
    r = ReplayClock(100, 25, clock=clk)
    r.play()
    clk.advance(100)
    assert r.position() == 99
    assert not r.playing
    assert r.ended
    r.play()  # restart from the beginning
    assert r.position() == 0


def test_invalid_speed(clk):
    r = ReplayClock(100, 25, clock=clk)
    with pytest.raises(ValueError):
        r.set_speed(3.0)
