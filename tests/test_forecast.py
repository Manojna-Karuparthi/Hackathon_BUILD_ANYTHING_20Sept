"""Forecast-layer tests.

The prediction claims are the easiest thing in this project to oversell, so
they are pinned down here: monotonicity, lead-time decay, the published
aftershock behaviour, and the refusal to forecast where a forecast would be
meaningless.
"""
import pytest

from backend.config import settings
from backend.engine.forecast import (
    aftershock_probability,
    band_for,
    forecast_aftershock,
    forecast_flood,
    forecast_heat,
    forecast_landslide,
)
from backend.zones import get_zone


# --- flood ---------------------------------------------------------------
def test_flood_probability_rises_with_forecast_rain():
    z = get_zone("in-sivasagar")
    probs = [
        forecast_flood(z, {"forecast_24h_mm": mm, "rain_24h_mm": 40}, 35.0, 24).probability
        for mm in (0, 30, 60, 100, 160, 260)
    ]
    assert probs == sorted(probs), "probability must be monotonic in forecast rainfall"
    assert probs[0] < 0.15 and probs[-1] > 0.90


def test_flood_probability_decays_with_lead_time():
    """A 48h call must be less certain than a 6h call for identical rainfall."""
    z = get_zone("in-sivasagar")
    w = {"forecast_24h_mm": 200, "rain_24h_mm": 40}
    probs = [forecast_flood(z, w, 35.0, h).probability for h in (6, 12, 24, 48)]
    assert probs == sorted(probs, reverse=True)


def test_flood_alarm_fires_at_threshold():
    z = get_zone("in-sivasagar")
    f = forecast_flood(z, {"forecast_24h_mm": 260, "rain_24h_mm": 60}, 40.0, 24)
    assert f.probability >= settings.alarm_probability
    assert f.actionable and f.band == "IMMINENT"
    assert "Open-Meteo" in f.method, "the method must name its data source"
    assert f.basis, "a probability without a stated basis is not acceptable"


# --- aftershock (Reasenberg & Jones) -------------------------------------
def test_aftershock_matches_published_behaviour():
    """Bath's law: the largest aftershock runs ~1.2 below the mainshock, so
    P(M>=Mm) must be small and P(M>=Mm-2) must be large."""
    p_same, _ = aftershock_probability(6.0, 6.0, 0, 1)
    p_lower, _ = aftershock_probability(6.0, 4.0, 0, 1)
    assert p_same < 0.15
    assert p_lower > 0.90
    assert p_same < p_lower


def test_aftershock_grows_with_window_and_magnitude():
    windows = [aftershock_probability(6.0, 5.0, 0, d)[0] for d in (1, 3, 7, 30)]
    assert windows == sorted(windows)
    mags = [aftershock_probability(m, 5.0, 0, 1)[0] for m in (5.0, 6.0, 7.0)]
    assert mags == sorted(mags)


def test_aftershock_probability_is_bounded():
    p, _ = aftershock_probability(9.0, 2.0, 0, 365)
    assert 0.0 <= p <= 1.0


def test_no_aftershock_forecast_for_small_events():
    """Below M4 a generic sequence forecast is not meaningful, so none is given
    rather than a fabricated number."""
    ev = [{"magnitude": 2.9, "place": "x", "depth_km": 5, "lat": 28, "lon": 85,
           "time": "2026-09-20T00:00:00+00:00", "type": "earthquake"}]
    assert forecast_aftershock(ev) is None


# --- landslide -----------------------------------------------------------
def test_landslide_only_forecast_on_steep_terrain():
    """A landslide forecast for the Brahmaputra floodplain would be noise."""
    assert forecast_landslide(get_zone("in-golaghat"), {"forecast_24h_mm": 250}) is None
    assert forecast_landslide(get_zone("np-rasuwa"), {"forecast_24h_mm": 250}) is not None


def test_landslide_probability_rises_with_intensity():
    z = get_zone("np-rasuwa")
    probs = [
        forecast_landslide(z, {"forecast_24h_mm": mm, "rain_72h_mm": mm * 1.5}).probability
        for mm in (5, 40, 90, 180)
    ]
    assert probs == sorted(probs)
    assert "Caine" in forecast_landslide(z, {"forecast_24h_mm": 90}).method


# --- heat ----------------------------------------------------------------
def test_heat_uses_elevation_appropriate_threshold():
    plain = forecast_heat(get_zone("in-jorhat"), {"temp_max_c": 41})
    hills = forecast_heat(get_zone("np-langtang-head"), {"temp_max_c": 41})
    assert hills.probability > plain.probability, (
        "41C is far more anomalous at 4100 m than on the Assam plain"
    )


def test_no_heat_forecast_without_temperature():
    assert forecast_heat(get_zone("in-jorhat"), {}) is None


# --- bands ---------------------------------------------------------------
def test_bands_are_ordered_and_alarm_aligned():
    assert band_for(0.05) == "LOW"
    assert band_for(0.5) == "ELEVATED"
    assert band_for(0.75) == "HIGH"
    assert band_for(settings.alarm_probability) == "IMMINENT"
