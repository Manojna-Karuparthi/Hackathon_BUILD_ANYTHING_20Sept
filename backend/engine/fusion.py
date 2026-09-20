"""Channel fusion, downstream cascade, and blind-spot detection.

Three design decisions here, and each one is a direct answer to how the
26 August 2026 warning failed:

1. FUSE WITH MAX, NEVER MEAN. Averaging a screaming seismic channel with a
   silent rainfall channel produces a calm number. A mean is how a two-sensor
   system talks itself out of an alarm. We take the maximum and then ADD a
   bounded cross-term, so two moderate signals outrank one moderate signal but
   a quiet channel can never dilute a loud one.

2. PROPAGATE DOWNSTREAM IN TIME. A mass-movement detection upstream is a
   *scheduled* emergency downstream. Zones below the source inherit a decayed
   score plus an arrival estimate, so a district with clear skies and a normal
   river can still be moved to WARNING - with a countdown, which is the only
   thing that actually buys evacuation time.

3. SCORE THE COUNTERFACTUAL. Every zone is also scored the way a conventional
   rainfall-only system would score it. When dual-channel says WATCH or worse
   and single-channel says NORMAL, that zone is flagged as a BLIND SPOT. This
   is the system auditing the previous generation of systems, live, on screen.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..config import LEVEL_RANK, settings
from ..models import CascadeAlert, ChannelScore, ZoneRisk
from ..zones import Zone, downstream_paths, zone_index
from .curves import clamp, decay

# A cascade is only raised when the upstream geo channel is this confident.
CASCADE_TRIGGER = 45.0
# Spatial decay of a debris surge: it attenuates, but over a long way.
CASCADE_DECAY_KM = 260.0
# Above this source score, an upstream detachment is treated as CONFIRMED.
CASCADE_CONFIRM = 60.0
# Distance decays the expected peak discharge. It does not decay the fact that
# the water is coming. Once a detachment is confirmed, every zone in the direct
# flow path is floored at WATCH - and at WARNING inside an hour of arrival -
# regardless of how far downstream it sits. Leaving 700,000 people at NORMAL
# because they are 186 km away, when a surge is confirmed and inbound, is the
# same category of error this project exists to correct.
CASCADE_FLOOR_ETA_S = 3600.0


def fuse(hydro: float, geo: float, kappa: float = None) -> tuple[float, str]:
    """Combine two independent channels into one 0-100 score."""
    kappa = settings.fusion_kappa if kappa is None else kappa
    hi, lo = max(hydro, geo), min(hydro, geo)
    cross = kappa * (lo / 100.0) * (hi / 100.0) * 100.0
    total = clamp(hi + cross, 0.0, 100.0)

    if lo < 1:
        note = f"Single active channel; score carried by {'hydrology' if hydro >= geo else 'ground motion'} alone ({hi:.0f})."
    else:
        note = (
            f"max({hydro:.0f}, {geo:.0f}) = {hi:.0f}, plus {cross:.1f} cross-channel "
            f"amplification (k={kappa}). A mean would have reported "
            f"{(hydro + geo) / 2:.0f} and understated this."
        )
    return round(total, 1), note


def compute_cascades(
    geo_scores: dict[str, float], now: datetime | None = None
) -> dict[str, CascadeAlert]:
    """Map every downstream zone to its worst inherited upstream threat."""
    now = now or datetime.now(timezone.utc)
    idx = zone_index()
    paths = downstream_paths()
    best: dict[str, CascadeAlert] = {}

    for src_id, src_geo in geo_scores.items():
        if src_geo < CASCADE_TRIGGER:
            continue
        src = idx.get(src_id)
        if src is None:
            continue
        for dst_id, km, eta_s, path in paths.get(src_id, []):
            transferred = src_geo * settings.cascade_transfer * decay(km, CASCADE_DECAY_KM)
            existing = best.get(dst_id)
            if existing and existing.transferred_score >= transferred:
                continue
            effective_v = (km * 1000.0) / max(eta_s, 1.0)
            best[dst_id] = CascadeAlert(
                source_score=round(src_geo, 1),
                source_zone_id=src_id,
                source_zone_name=src.name,
                distance_km=round(km, 1),
                velocity_ms=round(effective_v, 2),
                eta_seconds=round(eta_s, 1),
                eta_iso=(now + timedelta(seconds=eta_s)).isoformat(),
                transferred_score=round(transferred, 1),
                path=path,
            )
    return best


def build_zone_risk(
    zone: Zone,
    hydro: ChannelScore,
    geo: ChannelScore,
    cascade: CascadeAlert | None,
    now: datetime,
    engine_mode: str = "dual",
) -> ZoneRisk:
    """Assemble the final per-zone verdict, including the legacy counterfactual."""
    effective_geo = geo.score
    if cascade is not None and cascade.transferred_score > effective_geo:
        effective_geo = cascade.transferred_score

    if engine_mode == "legacy":
        # Reproduce a conventional rainfall-only system exactly.
        score, note = round(hydro.score, 1), (
            "LEGACY ENGINE: rainfall and river discharge only. Ground-motion input "
            "is not connected - this is the configuration that was operational in "
            "the Trishuli valley on 26 August 2026."
        )
    else:
        score, note = fuse(hydro.score, effective_geo)
        if cascade is not None and cascade.transferred_score > geo.score:
            note += (
                f" Ground-motion term is INHERITED from {cascade.source_zone_name} "
                f"{cascade.distance_km:.0f} km upstream, arriving in "
                f"{cascade.eta_seconds / 60:.0f} min."
            )

    # Confirmed-detachment floor (see CASCADE_CONFIRM above).
    floored = False
    if (
        engine_mode != "legacy"
        and cascade is not None
        and cascade.source_score >= CASCADE_CONFIRM
    ):
        floor = (
            settings.band_warning
            if cascade.eta_seconds <= CASCADE_FLOOR_ETA_S
            else settings.band_watch
        )
        if score < floor:
            score = floor
            floored = True
            cascade.floored = True
            note += (
                f" Score floored to {floor:.0f} by confirmed-detachment policy: the "
                f"surge is inbound with {cascade.eta_seconds / 60:.0f} min of lead time, "
                f"so distance may not be allowed to decay this zone below "
                f"{'WARNING' if floor >= settings.band_warning else 'WATCH'}."
            )

    legacy_score = round(hydro.score, 1)
    level = settings.band_for(score)
    legacy_level = settings.band_for(legacy_score)
    blindspot = (
        LEVEL_RANK[level] >= LEVEL_RANK["WATCH"]
        and LEVEL_RANK[legacy_level] < LEVEL_RANK["WATCH"]
    )

    return ZoneRisk(
        zone_id=zone.id, name=zone.name, admin=zone.admin, country=zone.country,
        lat=zone.lat, lon=zone.lon, population=zone.population, wards=list(zone.wards),
        basin=zone.basin, river=zone.river,
        score=score, level=level,
        legacy_score=legacy_score, legacy_level=legacy_level, blindspot=blindspot,
        hydro=hydro, geo=geo, fusion_note=note, cascade=cascade,
        updated_at=now.isoformat(),
    )
