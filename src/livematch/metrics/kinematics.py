"""Distance, speed (Savitzky-Golay), sprints and high-intensity running."""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import savgol_coeffs

SPRINT_SPEED = 7.0  # m/s
HI_SPEED = 5.5  # m/s
MIN_EFFORT_S = 1.0  # an effort counts if the speed stays above threshold for >= 1 s
MAX_PLAYER_SPEED = 12.5  # m/s, above this the sample is treated as a tracking glitch
MAX_STEP_SPEED = 15.0  # m/s, larger frame-to-frame jumps reset the track


class Kinematics:
    """Vectorised incremental kinematics for ``n`` tracked objects.

    Speed is the first derivative of a Savitzky-Golay polynomial fitted on the
    last ``window`` samples (evaluated at the window centre, i.e. with a lag of
    ``window // 2`` frames). Distance is the sum of raw frame-to-frame steps,
    excluding gaps, period changes and implausible jumps.
    """

    def __init__(
        self,
        n: int,
        fps: float,
        window: int = 11,
        polyorder: int = 2,
        max_speed: float = MAX_PLAYER_SPEED,
        max_step_speed: float = MAX_STEP_SPEED,
    ) -> None:
        self.n = n
        self.fps = fps
        self.dt = 1.0 / fps
        self.window = window
        # coefficients ordered oldest -> newest, derivative at the window centre
        self._coef = savgol_coeffs(window, polyorder, deriv=1, delta=self.dt, use="dot")
        self.max_speed = max_speed
        self.max_step = max_step_speed * self.dt
        # coefficient vectors pre-rotated for every ring-buffer pointer position
        self._coef_rolled = [np.roll(self._coef, k) for k in range(window)]
        self._buf = np.zeros((window, n, 2))
        self._steps = np.zeros((window, n))
        self._ptr = 0
        self._run = np.zeros(n, dtype=np.int64)  # consecutive valid samples
        self._last = np.full((n, 2), np.nan)
        self._period: int | None = None
        self.distance = np.zeros(n)
        self.speed = np.zeros(n)  # current smoothed speed (0 when unknown)
        self.velocity = np.zeros((n, 2))
        self.max_speed_reached = np.zeros(n)
        self.last_step = np.zeros(n)
        self.centre_step = np.zeros(n)
        """Step of the frame the current speed refers to (``window // 2`` frames ago)."""

    def update(self, xy: np.ndarray, period: int) -> None:
        valid = ~np.isnan(xy[:, 0]) & ~np.isnan(xy[:, 1])
        if self._period is not None and period != self._period:
            self._run[:] = 0
            self._last[:] = np.nan
        self._period = period
        d = xy - self._last
        step = np.sqrt(d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1])
        good_step = step <= self.max_step  # False for NaN (gaps / new tracks)
        self.last_step = np.where(good_step, step, 0.0)
        self.distance += self.last_step
        # tracks that are new / gapped / jumped restart their smoothing window
        self._run = np.where(good_step, self._run + 1, valid.astype(np.int64))
        self._buf[self._ptr] = xy
        self._steps[self._ptr] = self.last_step
        self._ptr = (self._ptr + 1) % self.window
        self.centre_step = self._steps[(self._ptr - 1 - self.window // 2) % self.window]
        self._last = xy.copy()

        ready = self._run >= self.window
        if ready.any():
            coef = self._coef_rolled[self._ptr]
            vel = np.tensordot(coef, self._buf, axes=(0, 0))  # (n, 2)
            vel[~ready] = 0.0
            spd = np.sqrt(vel[:, 0] * vel[:, 0] + vel[:, 1] * vel[:, 1])
            bad = spd > self.max_speed
            if bad.any():
                vel[bad] = 0.0
                spd[bad] = 0.0
            self.velocity = vel
            self.speed = spd
            np.maximum(self.max_speed_reached, spd, out=self.max_speed_reached)
        else:
            self.velocity = np.zeros((self.n, 2))
            self.speed = np.zeros(self.n)


class EffortTracker:
    """Counts efforts above a speed threshold lasting at least ``min_duration_s``.

    The distance of an effort includes the frames before it qualified.
    """

    def __init__(self, n: int, fps: float, threshold: float, min_duration_s: float = MIN_EFFORT_S):
        self.threshold = threshold
        self.min_frames = max(1, int(round(min_duration_s * fps)))
        self._run = np.zeros(n, dtype=np.int64)
        self._pending = np.zeros(n)
        self.count = np.zeros(n, dtype=np.int64)
        self.distance = np.zeros(n)

    def update(self, speed: np.ndarray, step: np.ndarray) -> None:
        above = speed > self.threshold
        self._run = (self._run + 1) * above
        self._pending = (self._pending + step) * above
        qualified_now = self._run == self.min_frames
        self.count += qualified_now
        # once qualified, the pending distance moves into the total; afterwards
        # every further step of the effort is added directly
        self.distance += self._pending * qualified_now + step * (self._run > self.min_frames)


class PointKinematics:
    """Pure-Python version of :class:`Kinematics` for a single object (the ball).

    Avoids numpy overhead on tiny arrays; same Savitzky-Golay estimator.
    """

    def __init__(
        self,
        fps: float,
        window: int = 5,
        polyorder: int = 1,
        max_speed: float = 45.0,
        max_step_speed: float = 60.0,
    ) -> None:
        self.dt = 1.0 / fps
        self.window = window
        self._coef = savgol_coeffs(window, polyorder, deriv=1, delta=self.dt, use="dot").tolist()
        self.max_speed = max_speed
        self.max_step = max_step_speed * self.dt
        self._xs: list[float] = []
        self._ys: list[float] = []
        self._period: int | None = None
        self.distance = 0.0
        self.speed = 0.0
        self.max_speed_reached = 0.0

    def update(self, x: float, y: float, period: int) -> None:
        if x != x or y != y or period != self._period:  # NaN or new period
            self._xs.clear()
            self._ys.clear()
            self._period = period
            if x != x or y != y:
                self.speed = 0.0
                return
        if self._xs:
            step = math.hypot(x - self._xs[-1], y - self._ys[-1])
            if step > self.max_step:
                self._xs.clear()
                self._ys.clear()
            else:
                self.distance += step
        self._xs.append(x)
        self._ys.append(y)
        if len(self._xs) > self.window:
            del self._xs[0], self._ys[0]
        if len(self._xs) < self.window:
            self.speed = 0.0
            return
        vx = sum(c * v for c, v in zip(self._coef, self._xs, strict=True))
        vy = sum(c * v for c, v in zip(self._coef, self._ys, strict=True))
        spd = math.hypot(vx, vy)
        self.speed = spd if spd <= self.max_speed else 0.0
        self.max_speed_reached = max(self.max_speed_reached, self.speed)
