"""Shared normalisation curves.

One function, used everywhere, so that "how does a raw number become a score"
has exactly one answer we can put on a slide.
"""
from __future__ import annotations

import math

# Chosen so that x == threshold maps to 0.80. Rationale: crossing a published
# warning threshold should be clearly severe but must leave headroom, because
# real events overshoot thresholds by multiples and the score still has to
# discriminate between "heavy" and "catastrophic".
_K = 1.6094379124341003  # -ln(1 - 0.80)


def saturate(value: float | None, threshold: float) -> float:
    """Map a raw measurement onto 0-1 against a published threshold.

    Exponential saturation: 0 at zero, 0.80 at the threshold, asymptotic to 1.
    Monotonic and never clips, so a doubling of rainfall still moves the score.
    """
    if value is None or threshold <= 0:
        return 0.0
    if value <= 0:
        return 0.0
    return 1.0 - math.exp(-_K * (value / threshold))


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def decay(distance: float, scale: float) -> float:
    """Exponential spatial/temporal attenuation, 1.0 at zero distance."""
    if distance <= 0:
        return 1.0
    return math.exp(-distance / max(scale, 1e-6))
