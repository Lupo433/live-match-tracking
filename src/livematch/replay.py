"""Live simulator: turns a recorded match into a real-time stream of frames.

:class:`ReplayClock` maps wall-clock time to a (fractional) frame position,
with play / pause / seek / speed. It takes an injectable ``clock`` callable so
timing can be tested deterministically.
"""

from __future__ import annotations

import time
from collections.abc import Callable

ALLOWED_SPEEDS: tuple[float, ...] = (0.5, 1.0, 2.0, 5.0, 10.0)


class ReplayClock:
    """Real-time position of a replay.

    ``position()`` = anchor_frame + (now - anchor_time) * fps * speed while
    playing; the anchor is re-set on every state change so that speed changes
    and pauses never make the position jump.
    """

    def __init__(
        self,
        n_frames: int,
        fps: float,
        clock: Callable[[], float] = time.monotonic,
        speed: float = 1.0,
    ) -> None:
        if n_frames <= 0:
            raise ValueError("n_frames must be positive")
        self.n_frames = n_frames
        self.fps = fps
        self._clock = clock
        self._speed = speed
        self._playing = False
        self._anchor_frame = 0.0
        self._anchor_time = clock()

    # ---- state
    @property
    def playing(self) -> bool:
        if self._playing and self._raw_position() >= self.n_frames - 1:
            self._rebase()
            self._playing = False
        return self._playing

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def ended(self) -> bool:
        return self.position() >= self.n_frames - 1

    def _raw_position(self) -> float:
        if not self._playing:
            return self._anchor_frame
        elapsed = self._clock() - self._anchor_time
        return self._anchor_frame + elapsed * self.fps * self._speed

    def position(self) -> float:
        """Current fractional frame position, clamped to the match length."""
        return min(max(self._raw_position(), 0.0), float(self.n_frames - 1))

    def frame_index(self) -> int:
        return int(self.position())

    def _rebase(self) -> None:
        self._anchor_frame = self.position()
        self._anchor_time = self._clock()

    # ---- commands
    def play(self) -> None:
        if self.ended:
            self.seek(0)
        if not self._playing:
            self._anchor_time = self._clock()
            self._playing = True

    def pause(self) -> None:
        if self._playing:
            self._rebase()
            self._playing = False

    def seek(self, frame: float) -> None:
        self._anchor_frame = min(max(float(frame), 0.0), float(self.n_frames - 1))
        self._anchor_time = self._clock()

    def seek_seconds(self, seconds: float) -> None:
        self.seek(seconds * self.fps)

    def set_speed(self, speed: float) -> None:
        if speed not in ALLOWED_SPEEDS:
            raise ValueError(f"speed must be one of {ALLOWED_SPEEDS}")
        self._rebase()
        self._speed = speed
