"""Plain-language explanation of a zone's current level.

Deterministic, offline, and always available. When a Hugging Face token is
configured the same structured payload is also sent for a more fluent phrasing,
but this is the floor: the system can always say, in words, exactly why a zone
is the colour it is. "The AI decided" is not an acceptable answer when a
district officer has to justify moving people.
"""
from __future__ import annotations

from ..models import ZoneRisk

ACTIONS = {
    "NORMAL": "No action. Routine monitoring.",
    "ADVISORY": "Inform ward focal points. No movement required.",
    "WATCH": "Alert ward focal points and pre-position response teams. Warn riverside households.",
    "WARNING": "Activate public address and move people off the floodplain and riverbank now.",
    "EMERGENCY": "Immediate evacuation of the flood path. Assume no further warning time.",
}


def _fmt_eta(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} seconds"
    minutes = seconds / 60.0
    if minutes < 90:
        return f"{minutes:.0f} minutes"
    return f"{minutes / 60.0:.1f} hours"


def build_explanation(risk: ZoneRisk) -> str:
    parts: list[str] = []

    # 1. The headline driver.
    all_contribs = risk.hydro.contributions + risk.geo.contributions
    if all_contribs:
        top = max(all_contribs, key=lambda c: c.points)
        if top.points > 0.5:
            parts.append(f"{risk.name} is at {risk.level} ({risk.score:.0f}/100). Dominant driver: {top.detail}.")
        else:
            parts.append(f"{risk.name} is at {risk.level} ({risk.score:.0f}/100). No single input is elevated.")
    else:
        parts.append(f"{risk.name} is at {risk.level} ({risk.score:.0f}/100).")

    # 2. Runner-up, if it is materially contributing.
    ranked = sorted(all_contribs, key=lambda c: -c.points)
    if len(ranked) > 1 and ranked[1].points > 4:
        parts.append(f"Second factor: {ranked[1].detail}.")

    # 3. The cascade - the part that buys evacuation time.
    if risk.cascade and risk.cascade.transferred_score > risk.geo.score:
        c = risk.cascade
        parts.append(
            f"This is an INHERITED threat: ground motion was detected at {c.source_zone_name}, "
            f"{c.distance_km:.0f} km upstream. Estimated arrival here in {_fmt_eta(c.eta_seconds)} "
            f"at {c.velocity_ms:.1f} m/s average. Local rainfall is not the reason for this level."
        )

    # 3b. Policy floor, stated explicitly so nobody thinks a number was fudged.
    if risk.cascade and risk.cascade.floored:
        parts.append(
            "Level set by confirmed-detachment policy rather than by the local measurement: "
            "an upstream collapse is confirmed and inbound, so this zone is not allowed to "
            "sit below its policy floor on the grounds of distance alone."
        )

    # 4. The blind-spot callout.
    if risk.blindspot:
        parts.append(
            f"BLIND SPOT: a rainfall-only system would score this zone "
            f"{risk.legacy_score:.0f}/100 ({risk.legacy_level}) and would not have alerted."
        )

    # 5. What the operator does about it.
    parts.append(ACTIONS.get(risk.level, ACTIONS["NORMAL"]))

    return " ".join(parts)


def build_spoken(risk: ZoneRisk) -> str:
    """Short, unambiguous text for speech synthesis and loudspeaker relay.

    Written to be read aloud twice over a village PA system: no numbers that
    do not matter, no abbreviations, action first.
    """
    if risk.cascade and risk.cascade.transferred_score > risk.geo.score:
        return (
            f"Emergency flood warning for {risk.name}. "
            f"A large landslide or ice collapse has been detected upstream near "
            f"{risk.cascade.source_zone_name}. Water is expected to reach {risk.name} in "
            f"approximately {_fmt_eta(risk.cascade.eta_seconds)}. "
            f"Move away from the river immediately and go to higher ground. "
            f"Do not wait for rain. Repeat: move away from the river now."
        )
    if risk.level in {"WARNING", "EMERGENCY"}:
        return (
            f"Flood {risk.level.lower()} for {risk.name}. Risk level {risk.score:.0f} out of 100. "
            f"Heavy rainfall and rising river levels have been recorded. "
            f"Move away from low-lying areas and the riverbank now. "
            f"Repeat: move away from the river and low ground."
        )
    return (
        f"Flood watch for {risk.name}. Risk level {risk.score:.0f} out of 100. "
        f"Conditions are worsening. Stay alert and be ready to move."
    )


def build_headline(risk: ZoneRisk) -> str:
    if risk.cascade and risk.cascade.transferred_score > risk.geo.score:
        return (
            f"{risk.level}: upstream mass movement - {risk.name} impact in "
            f"{_fmt_eta(risk.cascade.eta_seconds)}"
        )
    driver = "ground motion" if risk.geo.score > risk.hydro.score else "rainfall and river discharge"
    return f"{risk.level}: {risk.name} at {risk.score:.0f}/100 on {driver}"
