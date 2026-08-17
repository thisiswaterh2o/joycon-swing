"""
Minimal pitch/hit loop. Deliberately dumb for now — a "pitch" is just
a timer, and a "hit" is whatever swing event lands inside the contact
window. Scoring/contact-quality logic can get as fancy as you want
once the detection side is trustworthy.
"""

import random
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from swing_detector import SwingEvent


class ContactQuality(Enum):
    MISS = auto()
    FOUL = auto()
    CONTACT = auto()
    SOLID = auto()


@dataclass
class PitchResult:
    swing: Optional[SwingEvent]
    contact_quality: ContactQuality
    timing_offset_ms: float  # negative = early, positive = late


@dataclass
class GameSession:
    pitches_thrown: int = 0
    results: list = field(default_factory=list)

    def score(self) -> int:
        weights = {
            ContactQuality.SOLID: 3,
            ContactQuality.CONTACT: 1,
            ContactQuality.FOUL: 0,
            ContactQuality.MISS: 0,
        }
        return sum(weights[r.contact_quality] for r in self.results)


class GameLoop:
    """
    Call start_pitch(), then feed swing events via register_swing()
    within the pitch window. resolve_pitch() grades the outcome.
    """

    CONTACT_WINDOW_MS = 400  # generous window for the prototype
    SOLID_WINDOW_MS = 80     # timing offset that counts as "solid"

    def __init__(self):
        self.session = GameSession()
        self._pitch_start_ts: Optional[float] = None
        self._pitch_arrival_ts: Optional[float] = None

    def start_pitch(self, min_delay=0.8, max_delay=2.0) -> float:
        """Returns the delay (sec) before the pitch 'arrives' — the player swings for this moment."""
        delay = random.uniform(min_delay, max_delay)
        self._pitch_start_ts = time.monotonic()
        self._pitch_arrival_ts = self._pitch_start_ts + delay
        self.session.pitches_thrown += 1
        return delay

    def resolve_pitch(self, swing: Optional[SwingEvent]) -> PitchResult:
        if swing is None or self._pitch_arrival_ts is None:
            result = PitchResult(swing=None, contact_quality=ContactQuality.MISS, timing_offset_ms=0.0)
            self.session.results.append(result)
            return result

        offset_ms = (swing.timestamp - self._pitch_arrival_ts) * 1000

        if abs(offset_ms) > self.CONTACT_WINDOW_MS:
            quality = ContactQuality.MISS
        elif abs(offset_ms) <= self.SOLID_WINDOW_MS:
            quality = ContactQuality.SOLID
        elif abs(offset_ms) <= self.CONTACT_WINDOW_MS / 2:
            quality = ContactQuality.CONTACT
        else:
            quality = ContactQuality.FOUL

        result = PitchResult(swing=swing, contact_quality=quality, timing_offset_ms=offset_ms)
        self.session.results.append(result)
        return result
