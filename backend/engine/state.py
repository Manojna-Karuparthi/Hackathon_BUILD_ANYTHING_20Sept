"""Alert state machine.

Raw scores oscillate. Sirens must not. Three mechanisms keep the output stable
enough to be trusted by people who will stop listening after the second false
alarm:

- HYSTERESIS: escalate at the band edge, de-escalate only once the score has
  fallen `hysteresis_drop` points BELOW it.
- MINIMUM DWELL: a level must hold for `min_dwell_s` before it may drop.
  Escalation is never delayed - only de-escalation.
- COOLDOWN: an unchanged level does not re-notify for `alert_cooldown_s`.

Escalation is always immediate. Every suppression mechanism here is one-way.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..config import LEVEL_RANK, settings


@dataclass
class ZoneState:
    zone_id: str
    level: str = "NORMAL"
    since: float = field(default_factory=time.time)
    last_notified_at: float = 0.0
    last_notified_level: str = "NORMAL"


@dataclass
class AlertDecision:
    should_notify: bool
    level: str
    previous_level: str
    reason: str
    escalation: bool


class AlertStateMachine:
    def __init__(self) -> None:
        self._states: dict[str, ZoneState] = {}

    def state(self, zone_id: str) -> ZoneState:
        return self._states.setdefault(zone_id, ZoneState(zone_id))

    def reset(self) -> None:
        self._states.clear()

    def evaluate(self, zone_id: str, score: float, now: float | None = None) -> AlertDecision:
        now = now or time.time()
        st = self.state(zone_id)
        raw_level = settings.band_for(score)
        prev = st.level

        raw_rank, prev_rank = LEVEL_RANK[raw_level], LEVEL_RANK[prev]

        if raw_rank > prev_rank:
            effective, reason = raw_level, "escalation (immediate)"
        elif raw_rank < prev_rank:
            # Candidate de-escalation: must clear hysteresis AND dwell.
            held = now - st.since
            edge = _lower_edge(prev)
            cleared = score < (edge - settings.hysteresis_drop)
            if not cleared:
                effective, reason = prev, (
                    f"held at {prev}: score {score:.0f} has not fallen "
                    f"{settings.hysteresis_drop:.0f} pts below the {edge:.0f} band edge"
                )
            elif held < settings.min_dwell_s:
                effective, reason = prev, (
                    f"held at {prev}: minimum dwell {settings.min_dwell_s:.0f}s not met "
                    f"({held:.0f}s elapsed)"
                )
            else:
                effective, reason = raw_level, "de-escalation (hysteresis and dwell cleared)"
        else:
            effective, reason = raw_level, "steady"

        changed = effective != prev
        if changed:
            st.level = effective
            st.since = now

        escalation = LEVEL_RANK[effective] > prev_rank
        should_notify = False

        if escalation and LEVEL_RANK[effective] >= LEVEL_RANK["WATCH"]:
            should_notify = True
        elif (
            LEVEL_RANK[effective] >= LEVEL_RANK["WARNING"]
            and effective == st.last_notified_level
            and (now - st.last_notified_at) >= settings.alert_cooldown_s
        ):
            should_notify = True
            reason += " (cooldown elapsed, re-notifying sustained warning)"

        if should_notify:
            st.last_notified_at = now
            st.last_notified_level = effective

        return AlertDecision(should_notify, effective, prev, reason, escalation)


def _lower_edge(level: str) -> float:
    return {
        "ADVISORY": settings.band_advisory,
        "WATCH": settings.band_watch,
        "WARNING": settings.band_warning,
        "EMERGENCY": settings.band_emergency,
    }.get(level, 0.0)
