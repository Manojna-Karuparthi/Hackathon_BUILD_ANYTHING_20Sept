"""Probabilistic forecasting - what happens NEXT, with a number attached.

This is the part that genuinely predicts, and it does so using published
methods rather than a model fitted to ten incidents. Three forecasters, each
citable:

1. FLOOD - probability of threshold exceedance. Takes the numerical weather
   prediction forecast that Open-Meteo already serves (ECMWF/GFS output - a
   real forecast produced by real atmospheric models), projects the zone's
   24-hour accumulation forward, rescores it through the SAME Channel A
   function, and converts the margin over the alert band into a probability
   with a logistic whose spread widens with lead time. Standard
   hydrometeorological exceedance forecasting.

2. AFTERSHOCK - Reasenberg & Jones (1989) with Omori-Utsu decay, which is the
   method USGS uses operationally. Given a mainshock, it gives the probability
   of at least one aftershock above a chosen magnitude in a time window. This
   is NOT earthquake prediction: it is conditional aftershock probability given
   an earthquake that has already happened, which is a solved problem.

3. LANDSLIDE - Caine (1980) rainfall intensity-duration threshold, the
   canonical empirical triggering relation, modulated by slope and antecedent
   saturation.

What this still is not: nobody can forecast a first earthquake, and nobody can
tell you the hour a glacier will fail. Where a hazard is genuinely
unforecastable the forecaster says so rather than inventing a number.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..config import settings
from ..zones import Zone
from .curves import clamp

# --- Reasenberg & Jones generic sequence parameters -----------------------
# Generic values; a real deployment calibrates these per tectonic region.
RJ_A = -1.67
RJ_B = 0.91
OMORI_P = 1.08
OMORI_C = 0.05  # days


@dataclass
class Forecast:
    hazard: str
    horizon_hours: float
    probability: float           # 0-1
    band: str                    # LOW | ELEVATED | HIGH | VERY_HIGH | IMMINENT
    method: str                  # the citable method name
    basis: str                   # the numbers that produced it
    actionable: bool             # does this cross the auto-alarm threshold
    expected_value: float | None = None
    expected_unit: str = ""


def band_for(p: float) -> str:
    if p >= settings.alarm_probability:
        return "IMMINENT"
    if p >= 0.90:
        return "VERY_HIGH"
    if p >= 0.70:
        return "HIGH"
    if p >= 0.40:
        return "ELEVATED"
    return "LOW"


def _logistic(margin: float, spread: float) -> float:
    """Convert a score margin over a threshold into a probability."""
    return 1.0 / (1.0 + math.exp(-margin / max(spread, 1e-6)))


# ---------------------------------------------------------------- flood ---
def forecast_flood(
    zone: Zone,
    weather: dict[str, Any] | None,
    current_score: float,
    horizon_hours: float = 24.0,
) -> Forecast:
    """Probability the zone crosses its WARNING band within the horizon."""
    weather = weather or {}
    forecast_rain = float(weather.get("forecast_24h_mm") or weather.get("forecast_6h_mm") or 0.0)
    current_24h = float(weather.get("rain_24h_mm") or 0.0)

    # Projected accumulation: what the NWP forecast says will fall, plus what
    # has not yet drained out of the current window. The carry-over is
    # discounted because a rolling 24h window sheds its oldest hours too.
    projected = forecast_rain + current_24h * 0.55
    ratio = projected / max(zone.rain_24h_threshold, 1e-6)

    # Run the projection through the SAME saturating curve and exposure
    # multiplier Channel A uses, so the projected score is directly comparable
    # to the live one and to the alert bands.
    exposure = 0.80 + 0.40 * zone.vulnerability
    projected_score = 100.0 * (1.0 - math.exp(-1.6094 * ratio)) * exposure

    # Deliberately NOT clamped to 100 before taking the margin: an extreme
    # forecast must keep pushing the probability up rather than flattening out
    # the moment the score would cap. The clamp is for display only.
    margin = projected_score - settings.band_warning

    # Forecast spread widens with lead time - NWP precipitation skill decays
    # over the first two days, so a 48h call is less certain than a 6h one.
    spread = 6.0 + 0.28 * horizon_hours
    p = _logistic(margin, spread)

    return Forecast(
        hazard="flood",
        horizon_hours=horizon_hours,
        probability=round(p, 4),
        band=band_for(p),
        method="NWP threshold-exceedance (Open-Meteo ECMWF/GFS forecast precipitation)",
        basis=(
            f"{forecast_rain:.0f} mm forecast over {horizon_hours:.0f}h plus "
            f"{current_24h * 0.55:.0f} mm carried from the current window = "
            f"{projected:.0f} mm against a {zone.rain_24h_threshold:.0f} mm threshold "
            f"({ratio:.2f}x). Projected score {min(projected_score, 100.0):.0f} vs WARNING "
            f"at {settings.band_warning:.0f}; forecast spread +/-{spread:.0f} over "
            f"{horizon_hours:.0f}h lead time."
        ),
        actionable=p >= settings.alarm_probability,
        expected_value=round(projected, 1),
        expected_unit="mm/24h",
    )


# ------------------------------------------------------------ aftershock ---
def aftershock_probability(
    mainshock_mag: float, min_mag: float, t_start_days: float, t_end_days: float
) -> tuple[float, float]:
    """Reasenberg-Jones / Omori-Utsu. Returns (probability, expected count).

    Rate of aftershocks at or above `min_mag`:
        lambda(t) = 10^(a + b(Mm - M)) * (t + c)^(-p)      [per day]
    Integrated over the window and turned into P(at least one) by a Poisson
    assumption.
    """
    if mainshock_mag <= 0 or t_end_days <= t_start_days:
        return 0.0, 0.0

    k = 10.0 ** (RJ_A + RJ_B * (mainshock_mag - min_mag))

    # Integral of (t + c)^(-p) over [t_start, t_end]
    if abs(1.0 - OMORI_P) < 1e-9:
        integral = math.log((t_end_days + OMORI_C) / (t_start_days + OMORI_C))
    else:
        e = 1.0 - OMORI_P
        integral = ((t_end_days + OMORI_C) ** e - (t_start_days + OMORI_C) ** e) / e

    expected = max(0.0, k * integral)
    return 1.0 - math.exp(-expected), expected


def forecast_aftershock(
    events: list[dict[str, Any]], horizon_hours: float = 24.0, min_mag: float = 5.0
) -> Forecast | None:
    """Aftershock outlook for the largest recent event in the region."""
    if not events:
        return None
    main = max(events, key=lambda e: e.get("magnitude") or 0.0)
    mag = float(main.get("magnitude") or 0.0)
    if mag < 4.0:
        return None  # below this a generic sequence forecast is not meaningful

    p, expected = aftershock_probability(mag, min_mag, 0.0, horizon_hours / 24.0)

    # Bath's law: the largest aftershock typically runs about 1.2 below the
    # mainshock. Worth stating because it frames what "likely" means here.
    bath = mag - 1.2

    return Forecast(
        hazard="earthquake",
        horizon_hours=horizon_hours,
        probability=round(p, 4),
        band=band_for(p),
        method="Reasenberg-Jones (1989) aftershock forecast with Omori-Utsu decay",
        basis=(
            f"Mainshock M{mag:.1f} at {main.get('place') or 'unknown location'}. "
            f"Generic sequence parameters a={RJ_A}, b={RJ_B}, p={OMORI_P}, c={OMORI_C}. "
            f"Expected {expected:.2f} events of M{min_mag:.1f}+ in the next "
            f"{horizon_hours:.0f}h. Bath's law puts the likely largest aftershock near "
            f"M{bath:.1f}."
        ),
        actionable=p >= settings.alarm_probability,
        expected_value=round(expected, 2),
        expected_unit=f"events M{min_mag:.1f}+",
    )


# ------------------------------------------------------------- landslide ---
def forecast_landslide(
    zone: Zone, weather: dict[str, Any] | None, horizon_hours: float = 24.0
) -> Forecast | None:
    """Caine (1980) intensity-duration threshold: I = 14.82 * D^-0.39.

    Only meaningful on steep terrain - a landslide forecast for the Brahmaputra
    floodplain would be noise, so flat zones get no forecast rather than a
    fabricated low number.
    """
    if zone.terrain_factor > 0.86:
        return None
    weather = weather or {}

    duration_h = max(horizon_hours, 1.0)
    forecast_rain = float(weather.get("forecast_24h_mm") or weather.get("forecast_6h_mm") or 0.0)
    intensity = forecast_rain / duration_h
    threshold_i = 14.82 * (duration_h ** -0.39)
    ratio = intensity / max(threshold_i, 1e-6)

    # Antecedent saturation shifts the threshold down: wet ground fails sooner.
    r72 = float(weather.get("rain_72h_mm") or 0.0)
    wetness = clamp(r72 / max(zone.rain_24h_threshold * 2.0, 1.0))
    effective_ratio = ratio * (1.0 + 0.45 * wetness)

    # Steeper terrain (lower factor) fails at a lower ratio.
    slope_gain = 1.0 + (0.86 - zone.terrain_factor) * 1.2
    p = _logistic((effective_ratio * slope_gain - 1.0) * 100.0, 26.0)

    return Forecast(
        hazard="landslide",
        horizon_hours=horizon_hours,
        probability=round(p, 4),
        band=band_for(p),
        method="Caine (1980) rainfall intensity-duration triggering threshold",
        basis=(
            f"Forecast intensity {intensity:.1f} mm/h over {duration_h:.0f}h against a "
            f"Caine threshold of {threshold_i:.1f} mm/h ({ratio:.2f}x). Antecedent "
            f"saturation {wetness:.0%} and slope class '{zone.terrain}' raise the "
            f"effective ratio to {effective_ratio * slope_gain:.2f}x."
        ),
        actionable=p >= settings.alarm_probability,
        expected_value=round(intensity, 2),
        expected_unit="mm/h",
    )


# ------------------------------------------------------------------ heat ---
def forecast_heat(
    zone: Zone, weather: dict[str, Any] | None, horizon_hours: float = 48.0
) -> Forecast | None:
    """Extreme-heat outlook. Included because heat kills more people annually
    than floods across South Asia and is the least alarmed-on hazard there."""
    weather = weather or {}
    tmax = weather.get("temp_max_c")
    if tmax is None:
        return None
    tmax = float(tmax)
    # IMD heatwave criteria for the plains: 40C, severe at 45C.
    threshold = 40.0 if zone.elevation_m < 1000 else 32.0
    p = _logistic(tmax - threshold, 2.4)
    return Forecast(
        hazard="heatwave",
        horizon_hours=horizon_hours,
        probability=round(p, 4),
        band=band_for(p),
        method="IMD heatwave temperature criteria vs forecast maximum",
        basis=(
            f"Forecast maximum {tmax:.1f}C over the next {horizon_hours:.0f}h against a "
            f"{threshold:.0f}C heatwave threshold for this elevation "
            f"({zone.elevation_m:.0f} m)."
        ),
        actionable=p >= settings.alarm_probability,
        expected_value=round(tmax, 1),
        expected_unit="C",
    )


def forecast_zone(
    zone: Zone,
    weather: dict[str, Any] | None,
    current_score: float,
    seismic: list[dict[str, Any]],
    horizon_hours: float = 24.0,
) -> list[Forecast]:
    """Every forecast that is meaningful for this zone, strongest first."""
    from ..sources.usgs import events_near

    out: list[Forecast | None] = [
        forecast_flood(zone, weather, current_score, horizon_hours),
        forecast_landslide(zone, weather, horizon_hours),
        forecast_heat(zone, weather, 48.0),
    ]
    if zone.geo_watch:
        near = events_near(seismic, zone, settings.geo_radius_km * 2.5)
        out.append(forecast_aftershock(near, horizon_hours))

    return sorted(
        [f for f in out if f is not None], key=lambda f: -f.probability
    )
