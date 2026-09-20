"""Channel A - hydrological risk.

Slow-onset, rainfall-and-river driven flooding: the Assam 2026 mechanism, and
the mechanism essentially every deployed South Asian early-warning system is
calibrated for. Five terms, fixed published weights, no fitted parameters -
there is nothing here that cannot be recomputed by hand on a whiteboard.
"""
from __future__ import annotations

from typing import Any

from ..models import ChannelScore, Contribution
from ..zones import Zone
from .curves import clamp, saturate

# Weights sum to 1.0. Accumulation and discharge dominate because they are the
# two variables published flood thresholds are actually written against;
# intensity and trend provide the lead time that accumulation alone cannot.
WEIGHTS = {
    "rain_1h": 0.22,
    "rain_24h": 0.28,
    "trend": 0.15,
    "discharge": 0.23,
    "saturation": 0.12,
}


def score_hydro(
    zone: Zone, weather: dict[str, Any] | None, discharge: dict[str, Any] | None
) -> ChannelScore:
    weather = weather or {}
    discharge = discharge or {}
    stale = not weather

    contributions: list[Contribution] = []

    # --- 1. Short-duration intensity (cloudburst signature) ---------------
    r1 = float(weather.get("rain_1h_mm") or 0.0)
    n1 = saturate(r1, zone.rain_1h_threshold)
    contributions.append(
        Contribution(
            key="rain_1h", label="Rainfall intensity (1h)", raw=round(r1, 1), unit="mm",
            normalised=round(n1, 3), weight=WEIGHTS["rain_1h"],
            points=round(n1 * WEIGHTS["rain_1h"] * 100, 1),
            detail=(
                f"{r1:.1f} mm in the last hour against a {zone.rain_1h_threshold:.0f} mm "
                f"cloudburst threshold for {zone.terrain} terrain"
            ),
        )
    )

    # --- 2. 24-hour accumulation (IMD/DHM category anchor) ----------------
    r24 = float(weather.get("rain_24h_mm") or 0.0)
    n24 = saturate(r24, zone.rain_24h_threshold)
    contributions.append(
        Contribution(
            key="rain_24h", label="Accumulation (24h)", raw=round(r24, 1), unit="mm",
            normalised=round(n24, 3), weight=WEIGHTS["rain_24h"],
            points=round(n24 * WEIGHTS["rain_24h"] * 100, 1),
            detail=(
                f"{r24:.1f} mm in 24h against a {zone.rain_24h_threshold:.0f} mm "
                f"'very heavy' threshold (IMD 115.6 mm scaled by terrain factor "
                f"{zone.terrain_factor:.2f})"
            ),
        )
    )

    # --- 3. Intensification trend ----------------------------------------
    trend = float(weather.get("trend_6h_mm") or 0.0)
    trend_threshold = max(zone.rain_24h_threshold * 0.35, 5.0)
    ntrend = saturate(max(trend, 0.0), trend_threshold)
    direction = "intensifying" if trend > 1 else ("easing" if trend < -1 else "flat")
    contributions.append(
        Contribution(
            key="trend", label="Trend (last 6h vs previous 6h)", raw=round(trend, 1),
            unit="mm", normalised=round(ntrend, 3), weight=WEIGHTS["trend"],
            points=round(ntrend * WEIGHTS["trend"] * 100, 1),
            detail=(
                f"Rainfall is {direction}: {trend:+.1f} mm change between consecutive "
                f"6-hour windows. Only rising trends add risk."
            ),
        )
    )

    # --- 4. River discharge anomaly (GloFAS) ------------------------------
    ratio = discharge.get("anomaly_ratio")
    if ratio is None:
        ndis, raw_ratio = 0.0, None
        dis_detail = "No modelled discharge available for this reach; term contributes 0."
    else:
        raw_ratio = float(ratio)
        # 1.0x = seasonal normal. 2.5x normal is the anchor for a major flood.
        ndis = saturate(max(raw_ratio - 1.0, 0.0), 1.5)
        cur = discharge.get("discharge_m3s")
        base = discharge.get("baseline_m3s")
        dis_detail = (
            f"River discharge {cur:.0f} m3/s against a {base:.0f} m3/s seasonal normal "
            f"({raw_ratio:.2f}x)" if cur and base else f"Discharge anomaly {raw_ratio:.2f}x normal"
        )
    contributions.append(
        Contribution(
            key="discharge", label="River discharge anomaly", raw=raw_ratio, unit="x normal",
            normalised=round(ndis, 3), weight=WEIGHTS["discharge"],
            points=round(ndis * WEIGHTS["discharge"] * 100, 1), detail=dis_detail,
        )
    )

    # --- 5. Antecedent saturation ----------------------------------------
    r72 = float(weather.get("rain_72h_mm") or 0.0)
    soil = weather.get("soil_moisture")
    nsat_rain = saturate(r72, zone.rain_24h_threshold * 2.5)
    nsat_soil = clamp(float(soil) / 0.45) if soil is not None else nsat_rain
    nsat = clamp(0.6 * nsat_rain + 0.4 * nsat_soil)
    soil_txt = f", soil moisture {soil:.2f} m3/m3" if soil is not None else ""
    contributions.append(
        Contribution(
            key="saturation", label="Antecedent saturation (72h)", raw=round(r72, 1),
            unit="mm", normalised=round(nsat, 3), weight=WEIGHTS["saturation"],
            points=round(nsat * WEIGHTS["saturation"] * 100, 1),
            detail=(
                f"{r72:.1f} mm over 72h{soil_txt}. Saturated ground converts far more "
                f"of the next storm into runoff."
            ),
        )
    )

    hazard = sum(c.points for c in contributions)

    # Exposure multiplier: identical rainfall is not an identical emergency in
    # a dense riverside bazaar and an empty high valley. Bounded 0.80-1.20 so
    # exposure shades the score without ever inventing a hazard.
    exposure = 0.80 + 0.40 * zone.vulnerability
    score = clamp(hazard * exposure, 0.0, 100.0)

    top = max(contributions, key=lambda c: c.points)
    if score < 1:
        summary = "No meaningful rainfall or discharge signal."
    else:
        summary = (
            f"Driven by {top.label.lower()} ({top.points:.0f} of {score:.0f} pts); "
            f"exposure multiplier {exposure:.2f}x for {zone.name}."
        )

    return ChannelScore(
        channel="HYDRO",
        score=round(score, 1),
        confidence=0.45 if stale else 1.0,
        contributions=contributions,
        inputs_stale=stale,
        summary=summary,
    )
