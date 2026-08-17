"""
Swing detection: option 1 from planning — orientation fusion, no
absolute position tracking. Peak accel magnitude triggers a candidate
swing window; gyro-derived orientation gives angle at "contact."

This is intentionally simple to start. Tune thresholds once we have
real baseline + swing data logged tomorrow.
"""

import math
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

import config
from joycon_reader import ImuSample


class SwingPhase(Enum):
    IDLE = auto()
    IN_SWING = auto()
    REFRACTORY = auto()


@dataclass
class SwingEvent:
    timestamp: float
    peak_accel_magnitude: float
    peak_gyro_magnitude: float
    duration_ms: float
    estimated_angle_deg: float  # from orientation fusion at peak


def accel_magnitude(sample: ImuSample) -> float:
    return math.sqrt(sample.accel_x**2 + sample.accel_y**2 + sample.accel_z**2)


def gyro_magnitude(sample: ImuSample) -> float:
    return math.sqrt(sample.gyro_x**2 + sample.gyro_y**2 + sample.gyro_z**2)


class ComplementaryFilter:
    """
    Fuses accel + gyro into a running orientation estimate (pitch/roll).
    No position tracking — orientation only, per the plan.
    """

    def __init__(self, alpha: float = config.COMPLEMENTARY_FILTER_ALPHA):
        self.alpha = alpha
        self.pitch = 0.0
        self.roll = 0.0
        self._last_ts: Optional[float] = None

    def update(self, sample: ImuSample) -> None:
        now = sample.timestamp
        dt = 0.0 if self._last_ts is None else now - self._last_ts
        self._last_ts = now

        # Accel-derived angle (noisy but no drift)
        accel_pitch = math.degrees(
            math.atan2(sample.accel_y, math.sqrt(sample.accel_x**2 + sample.accel_z**2))
        )
        accel_roll = math.degrees(
            math.atan2(-sample.accel_x, sample.accel_z)
        )

        # Gyro-derived delta (smooth but drifts) — raw gyro units need a
        # scale factor to deg/sec; placeholder divisor until calibrated.
        gyro_scale = 1000.0
        gyro_pitch_rate = sample.gyro_x / gyro_scale
        gyro_roll_rate = sample.gyro_y / gyro_scale

        if dt == 0.0:
            self.pitch, self.roll = accel_pitch, accel_roll
        else:
            self.pitch = self.alpha * (self.pitch + gyro_pitch_rate * dt) + (1 - self.alpha) * accel_pitch
            self.roll = self.alpha * (self.roll + gyro_roll_rate * dt) + (1 - self.alpha) * accel_roll


class SwingDetector:
    def __init__(self):
        self.phase = SwingPhase.IDLE
        self.filter = ComplementaryFilter()
        self._swing_start_ts: Optional[float] = None
        self._peak_accel = 0.0
        self._peak_gyro = 0.0
        self._peak_angle = 0.0
        self._refractory_until = 0.0

    def process(self, sample: ImuSample) -> Optional[SwingEvent]:
        self.filter.update(sample)
        accel_mag = accel_magnitude(sample)
        gyro_mag = gyro_magnitude(sample)
        now = sample.timestamp

        if self.phase == SwingPhase.REFRACTORY:
            if now >= self._refractory_until:
                self.phase = SwingPhase.IDLE
            return None

        if self.phase == SwingPhase.IDLE:
            if accel_mag > config.ACCEL_MAGNITUDE_SWING_THRESHOLD:
                self.phase = SwingPhase.IN_SWING
                self._swing_start_ts = now
                self._peak_accel = accel_mag
                self._peak_gyro = gyro_mag
                self._peak_angle = self.filter.pitch
            return None

        if self.phase == SwingPhase.IN_SWING:
            elapsed_ms = (now - self._swing_start_ts) * 1000

            if accel_mag > self._peak_accel:
                self._peak_accel = accel_mag
                self._peak_angle = self.filter.pitch
            self._peak_gyro = max(self._peak_gyro, gyro_mag)

            if elapsed_ms > config.SWING_WINDOW_MS:
                event = SwingEvent(
                    timestamp=self._swing_start_ts,
                    peak_accel_magnitude=self._peak_accel,
                    peak_gyro_magnitude=self._peak_gyro,
                    duration_ms=elapsed_ms,
                    estimated_angle_deg=self._peak_angle,
                )
                self.phase = SwingPhase.REFRACTORY
                self._refractory_until = now + config.REFRACTORY_MS / 1000
                return event

        return None
