"""Engine behaviour tests.

These encode the claims the pitch makes. If one of them fails, a sentence in
the README has become false.
"""
from datetime import datetime, timezone

import pytest

from backend.engine.curves import saturate
from backend.engine.fusion import compute_cascades, fuse
from backend.engine.geo import score_geo
from backend.engine.hydro import score_hydro
from backend.engine.state import AlertStateMachine
from backend.zones import get_zone, downstream_paths

NOW = datetime.now(timezone.utc)


def ev(mag=3.8, depth=1.2, lat=28.2556, lon=85.5194, etype="landslide", place="Langtang"):
    return {
        "id": "t", "magnitude": mag, "depth_km": depth, "lat": lat, "lon": lon,
        "place": place, "time": NOW.isoformat(), "type": etype, "mag_type": "ml",
    }


# --- curves ---------------------------------------------------------------
def test_saturation_hits_080_at_threshold():
    assert saturate(100.0, 100.0) == pytest.approx(0.80, abs=1e-3)


def test_saturation_is_monotonic_and_bounded():
    prev = 0.0
    for x in range(0, 500, 10):
        v = saturate(float(x), 100.0)
        assert v >= prev
        assert 0.0 <= v <= 1.0
        prev = v


# --- channel A ------------------------------------------------------------
def test_hydro_quiet_conditions_score_low():
    z = get_zone("in-sivasagar")
    s = score_hydro(z, {"rain_1h_mm": 0.1, "rain_24h_mm": 3, "rain_72h_mm": 9}, {})
    assert s.score < 15


def test_hydro_extreme_rain_reaches_emergency_band():
    z = get_zone("in-sivasagar")
    s = score_hydro(
        z,
        {"rain_1h_mm": 48, "rain_24h_mm": 205, "rain_72h_mm": 330,
         "trend_6h_mm": 60, "soil_moisture": 0.44},
        {"anomaly_ratio": 2.8, "discharge_m3s": 1500, "baseline_m3s": 530},
    )
    assert s.score >= 85


def test_hydro_contributions_sum_to_hazard_before_exposure():
    z = get_zone("in-jorhat")
    s = score_hydro(z, {"rain_1h_mm": 20, "rain_24h_mm": 90}, {"anomaly_ratio": 1.6})
    exposure = 0.80 + 0.40 * z.vulnerability
    assert s.score == pytest.approx(sum(c.points for c in s.contributions) * exposure, abs=0.2)


# --- channel B ------------------------------------------------------------
def test_geo_detects_mass_movement_signature():
    s = score_geo(get_zone("np-langtang-head"), [ev()], NOW)
    assert s.score >= 55, "a shallow non-tectonic event on the glacier must register"


def test_geo_ignores_distant_tectonic_quake():
    """The proximity gate is multiplicative - this is the false-positive guard."""
    far = ev(mag=5.4, depth=42, lat=27.0, lon=87.5, etype="earthquake", place="far")
    assert score_geo(get_zone("np-langtang-head"), [far], NOW).score < 5


def test_geo_silent_for_non_watch_zones():
    assert score_geo(get_zone("in-golaghat"), [ev()], NOW).score == 0.0


def test_geo_deep_event_scores_below_shallow_event():
    shallow = score_geo(get_zone("np-langtang-head"), [ev(depth=1.0)], NOW).score
    deep = score_geo(get_zone("np-langtang-head"), [ev(depth=30.0)], NOW).score
    assert shallow > deep


# --- fusion ---------------------------------------------------------------
def test_fusion_never_dilutes_a_loud_channel():
    """The core claim: a silent channel must not pull the score down.

    This is the exact failure this project exists to correct - an averaging
    fusion would report 36 here.
    """
    score, _ = fuse(0.0, 72.0)
    assert score >= 72.0
    assert score > (0.0 + 72.0) / 2


def test_fusion_amplifies_two_moderate_channels():
    both, _ = fuse(58.0, 61.0)
    one, _ = fuse(0.0, 61.0)
    assert both > one


def test_fusion_is_bounded():
    assert fuse(100.0, 100.0)[0] <= 100.0


# --- cascade --------------------------------------------------------------
def test_cascade_reaches_every_downstream_zone():
    c = compute_cascades({"np-langtang-head": 88.0}, NOW)
    assert {"np-rasuwa", "np-nuwakot", "np-dhading", "np-gorkha", "np-chitwan"} <= set(c)


def test_cascade_eta_increases_with_distance():
    c = compute_cascades({"np-langtang-head": 88.0}, NOW)
    etas = [c[z].eta_seconds for z in
            ["np-rasuwa", "np-nuwakot", "np-dhading", "np-gorkha", "np-chitwan"]]
    assert etas == sorted(etas)


def test_cascade_gives_rasuwa_usable_lead_time():
    """The whole value proposition is lead time. Assert it is real."""
    c = compute_cascades({"np-langtang-head": 88.0}, NOW)
    assert 15 * 60 <= c["np-rasuwa"].eta_seconds <= 45 * 60


def test_cascade_does_not_flow_upstream():
    c = compute_cascades({"np-chitwan": 90.0}, NOW)
    assert "np-langtang-head" not in c and "np-rasuwa" not in c


def test_no_cascade_below_trigger():
    assert compute_cascades({"np-langtang-head": 20.0}, NOW) == {}


def test_basin_graph_is_acyclic():
    for zid, paths in downstream_paths().items():
        assert zid not in {p[0] for p in paths}, f"{zid} is downstream of itself"


# --- state machine --------------------------------------------------------
def test_escalation_is_immediate():
    m = AlertStateMachine()
    d = m.evaluate("z", 90.0, 1000.0)
    assert d.level == "EMERGENCY" and d.should_notify


def test_hysteresis_blocks_flapping():
    m = AlertStateMachine()
    m.evaluate("z", 75.0, 1000.0)
    held = m.evaluate("z", 67.0, 1010.0)
    assert held.level == "WARNING", "must not drop while inside the hysteresis band"


def test_deescalation_requires_dwell_and_hysteresis():
    m = AlertStateMachine()
    m.evaluate("z", 75.0, 1000.0)
    assert m.evaluate("z", 30.0, 1005.0).level == "WARNING"   # dwell not met
    assert m.evaluate("z", 30.0, 2000.0).level == "NORMAL"    # both cleared


def test_advisory_alone_does_not_notify():
    m = AlertStateMachine()
    assert not m.evaluate("z", 45.0, 1000.0).should_notify
