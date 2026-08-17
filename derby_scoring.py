"""
Home Run Derby swing scoring simulator.
Uses calibration-based (self-relative) power scoring + a timing/contact model.
Run standalone to test against sample swings; swap in real capture data later.
"""

import random
import numpy as np


class SwingCalibration:
    """Run once per player (or per session) to normalize scoring to their
    own natural swing range, rather than a hardcoded dps threshold."""

    def __init__(self, calibration_swings_peak_gyro):
        # calibration_swings_peak_gyro: list of peak gyro_mag values from
        # a batting-practice session (mix of soft to full-effort swings)
        self.floor = min(calibration_swings_peak_gyro)
        self.ceiling = max(calibration_swings_peak_gyro)
        print(f"Calibrated: floor={self.floor:.0f}dps  ceiling={self.ceiling:.0f}dps")

    def normalize_power(self, peak_gyro, peak_accel=None):
        """Returns 0.0-1.0 power score relative to this player's own range."""
        span = max(self.ceiling - self.floor, 1e-6)
        raw = (peak_gyro - self.floor) / span
        return float(np.clip(raw, 0.0, 1.0))


class PitchDifficulty:
    """Two independent knobs: pitch speed (affects reaction time available)
    and contact window size (affects timing precision required)."""

    PRESETS = {
        "easy":   {"pitch_speed_mph": 55, "window_ms": 220},
        "medium": {"pitch_speed_mph": 75, "window_ms": 140},
        "hard":   {"pitch_speed_mph": 95, "window_ms": 80},
    }

    def __init__(self, pitch_speed_mph=None, window_ms=None, preset=None):
        if preset:
            cfg = self.PRESETS[preset]
            pitch_speed_mph = pitch_speed_mph or cfg["pitch_speed_mph"]
            window_ms = window_ms or cfg["window_ms"]
        self.pitch_speed_mph = pitch_speed_mph or 75
        self.window_ms = window_ms or 140


def score_swing(timing_offset_ms, peak_gyro, difficulty: PitchDifficulty, calibration: SwingCalibration):
    """
    timing_offset_ms: how far off the swing's motion-onset was from ideal
                       contact time (0 = perfect, negative = early, positive = late)
    Returns a result dict with outcome tier + estimated distance.
    """
    half_window = difficulty.window_ms / 2

    if abs(timing_offset_ms) > half_window:
        return {"outcome": "WHIFF", "distance_ft": 0, "timing_quality": 0.0, "power": None}

    # timing_quality: 1.0 at dead center, falls off toward window edges
    timing_quality = 1.0 - (abs(timing_offset_ms) / half_window)

    power = calibration.normalize_power(peak_gyro)
    combined = power * (0.5 + 0.5 * timing_quality)  # timing softens power, doesn't zero it out inside the window

    # crude distance curve: 100ft floor for weak contact, 480ft ceiling for perfect
    distance = 100 + combined * 380

    if timing_quality > 0.85 and power > 0.8:
        tier = "SWEET SPOT"
    elif combined > 0.5:
        tier = "SOLID CONTACT"
    else:
        tier = "WEAK CONTACT"

    return {
        "outcome": tier,
        "distance_ft": round(distance),
        "timing_quality": round(timing_quality, 2),
        "power": round(power, 2),
    }


if __name__ == "__main__":
    # Calibration from your real captured peak_gyro values (mixed intensity batch)
    calibration_data = [785, 812, 988, 1058, 1097, 1171, 1243, 1257, 1354, 1481,
                         1780, 1872, 1935, 2433]
    calib = SwingCalibration(calibration_data)

    print("\n--- Sample derby round: medium difficulty ---")
    difficulty = PitchDifficulty(preset="medium")

    # simulate a handful of swings with varied timing + power
    test_swings = [
        {"timing_offset_ms": 5, "peak_gyro": 2200},    # near-perfect timing, huge power
        {"timing_offset_ms": 60, "peak_gyro": 1900},   # late-ish, still strong
        {"timing_offset_ms": -100, "peak_gyro": 1500}, # early, outside window at medium
        {"timing_offset_ms": 20, "peak_gyro": 900},    # good timing, weak power
        {"timing_offset_ms": 0, "peak_gyro": 800},     # perfect timing, floor power
    ]

    for i, swing in enumerate(test_swings):
        result = score_swing(swing["timing_offset_ms"], swing["peak_gyro"], difficulty, calib)
        print(f"Swing {i+1}: offset={swing['timing_offset_ms']:+d}ms peak={swing['peak_gyro']}dps"
              f"  -->  {result['outcome']}  ({result['distance_ft']}ft)"
              f"  [timing={result['timing_quality']}, power={result['power']}]")
