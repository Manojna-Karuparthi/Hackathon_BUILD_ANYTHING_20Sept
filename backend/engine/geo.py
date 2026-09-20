"""Channel B - ground-motion / mass-movement risk.

This is the channel Nepal's operational system did not have on 26 August 2026.
Its job is NOT to forecast earthquakes. It is to recognise, from a seismic
waveform catalogue, the signature of a mountain moving: a shallow, moderate,
non-tectonic release inside a glaciated or steeply-jointed catchment.

The four terms below are combined additively and then GATED by proximity,
because an M5 two hundred kilometres away is geologically interesting and
operationally irrelevant. Additive-only fusion of a distant event is precisely
the sort of false positive that gets a warning system switched off.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..config import settings
from ..models import ChannelScore, Contribution
from ..sources.usgs import events_near
from ..zones import Zone
from .curves import clamp, decay, saturate

WEIGHTS = {
    "energy": 0.28,
    "shallow": 0.22,
    "signature": 0.34,
    "cluster": 0.16,
}

# A mass-movement seismic source sits in this magnitude window. Below it the
# signal is indistinguishable from background; above it the event is a genuine
# tectonic earthquake and a different response applies.
MASS_MOVEMENT_MAG = (1.8, 4.8)
MASS_MOVEMENT_DEPTH_KM = 10.0


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def mass_movement_signature(event: dict[str, Any], zone: Zone) -> tuple[float, list[str]]:
    """How much does this event look like ice/rock failure rather than a fault?

    Returns 0-1 plus the human-readable reasons, which go straight into the
    dashboard's explainability panel.
    """
    reasons: list[str] = []
    score = 0.0

    mag = event["magnitude"]
    depth = event["depth_km"]

    if MASS_MOVEMENT_MAG[0] <= mag <= MASS_MOVEMENT_MAG[1]:
        score += 0.30
        reasons.append(
            f"M{mag:.1f} sits in the {MASS_MOVEMENT_MAG[0]}-{MASS_MOVEMENT_MAG[1]} "
            f"window typical of slope failure, not tectonic rupture"
        )
    elif mag > MASS_MOVEMENT_MAG[1]:
        reasons.append(f"M{mag:.1f} is large enough to be a tectonic event in its own right")
        score += 0.10

    if depth <= MASS_MOVEMENT_DEPTH_KM:
        shallow_bonus = 0.30 * (1.0 - depth / MASS_MOVEMENT_DEPTH_KM)
        score += shallow_bonus
        reasons.append(
            f"focal depth {depth:.1f} km is at or near the surface - consistent with "
            f"mass detaching, not a fault at depth"
        )

    if zone.cryosphere.get("glacier_area_km2"):
        score += 0.25
        reasons.append(
            f"{zone.cryosphere['glacier_area_km2']:.0f} km2 of glacier ice and "
            f"{zone.cryosphere.get('glacial_lakes', 0)} mapped glacial lakes upslope"
        )
    elif zone.terrain.startswith(("high-mountain", "mountain")):
        score += 0.12
        reasons.append("steep mountain catchment with known slope instability")

    if event.get("type") and event["type"] not in {"earthquake", ""}:
        score += 0.15
        reasons.append(f"catalogued as '{event['type']}', not a standard earthquake")

    return clamp(score), reasons


def score_geo(
    zone: Zone, events: list[dict[str, Any]], now: datetime | None = None
) -> ChannelScore:
    now = now or datetime.now(timezone.utc)

    if not zone.geo_watch:
        return ChannelScore(
            channel="GEO",
            score=0.0,
            confidence=1.0,
            contributions=[],
            summary=(
                "Zone is outside the ground-motion watch set (low-relief terrain, no "
                "upslope ice or unstable mass). Risk here arrives by river, not by slope."
            ),
        )

    near = events_near(events, zone, settings.geo_radius_km)
    if not near:
        return ChannelScore(
            channel="GEO",
            score=0.0,
            confidence=1.0,
            contributions=[],
            summary=(
                f"No catalogued ground motion within {settings.geo_radius_km:.0f} km in "
                f"the last 24 hours."
            ),
        )

    primary = max(near, key=lambda e: e["magnitude"] * decay(e["distance_km"], 45.0))
    sig, reasons = mass_movement_signature(primary, zone)

    contributions: list[Contribution] = []

    # --- 1. Released energy ----------------------------------------------
    mag = primary["magnitude"]
    n_energy = clamp((mag - 1.0) / 4.5)
    contributions.append(
        Contribution(
            key="energy", label="Seismic energy", raw=round(mag, 1), unit="M",
            normalised=round(n_energy, 3), weight=WEIGHTS["energy"],
            points=round(n_energy * WEIGHTS["energy"] * 100, 1),
            detail=(
                f"M{mag:.1f} {primary.get('mag_type','')} event {primary['distance_km']:.0f} km "
                f"away at {primary['place'] or 'unnamed location'}"
            ),
        )
    )

    # --- 2. Shallowness ---------------------------------------------------
    depth = primary["depth_km"]
    n_shallow = decay(depth, 8.0)
    contributions.append(
        Contribution(
            key="shallow", label="Focal shallowness", raw=round(depth, 1), unit="km",
            normalised=round(n_shallow, 3), weight=WEIGHTS["shallow"],
            points=round(n_shallow * WEIGHTS["shallow"] * 100, 1),
            detail=(
                f"{depth:.1f} km depth. Surface-rupturing mass movement concentrates "
                f"above 5 km; deep events shake but do not detach slopes."
            ),
        )
    )

    # --- 3. Non-tectonic signature (the decisive term) -------------------
    contributions.append(
        Contribution(
            key="signature", label="Mass-movement signature", raw=round(sig, 2), unit="",
            normalised=round(sig, 3), weight=WEIGHTS["signature"],
            points=round(sig * WEIGHTS["signature"] * 100, 1),
            detail="; ".join(reasons) if reasons else "No mass-movement indicators matched.",
        )
    )

    # --- 4. Temporal clustering ------------------------------------------
    recent = [e for e in near if (now - _parse_time(e["time"])).total_seconds() <= 3600]
    n_cluster = saturate(float(len(recent)), 4.0)
    contributions.append(
        Contribution(
            key="cluster", label="Event clustering (1h)", raw=float(len(recent)), unit="events",
            normalised=round(n_cluster, 3), weight=WEIGHTS["cluster"],
            points=round(n_cluster * WEIGHTS["cluster"] * 100, 1),
            detail=(
                f"{len(recent)} event(s) within {settings.geo_radius_km:.0f} km in the last "
                f"hour. Progressive failure arrives as a swarm, not a single shock."
            ),
        )
    )

    base = sum(c.points for c in contributions)

    # Proximity gate - multiplicative, never additive.
    gate = decay(primary["distance_km"], 45.0)
    score = clamp(base * gate, 0.0, 100.0)

    summary = (
        f"M{mag:.1f} at {depth:.1f} km depth, {primary['distance_km']:.0f} km away. "
        f"Mass-movement signature {sig:.0%}; proximity gate {gate:.2f}x."
    )

    return ChannelScore(
        channel="GEO",
        score=round(score, 1),
        confidence=1.0,
        contributions=contributions,
        summary=summary,
    )
