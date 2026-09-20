"""Scenario-level tests: the two claims the demo makes, asserted end to end."""
from datetime import datetime, timezone

from backend.config import LEVEL_RANK, settings
from backend.engine.analogue import find_analogues
from backend.engine.fusion import build_zone_risk, compute_cascades
from backend.engine.geo import score_geo
from backend.engine.hydro import score_hydro
from backend.sources.replay import ReplayCursor, list_scenarios
from backend.zones import zones


def run_frame(cursor, engine_mode="dual"):
    now = datetime.now(timezone.utc)
    frame = cursor.frame(now)
    hyd, geo, raw = {}, {}, {}
    for z in zones():
        hyd[z.id] = score_hydro(z, frame["weather"].get(z.id), frame["discharge"].get(z.id))
        geo[z.id] = score_geo(z, frame["seismic"], now)
        raw[z.id] = geo[z.id].score
    casc = compute_cascades(raw, now)
    return {
        z.id: build_zone_risk(z, hyd[z.id], geo[z.id], casc.get(z.id), now, engine_mode)
        for z in zones()
    }


def test_scenarios_load():
    ids = {s.id for s in list_scenarios()}
    assert {"live", "langtang-2026", "assam-2026"} <= ids


def test_langtang_is_quiet_before_the_collapse():
    c = ReplayCursor(); c.select("langtang-2026"); c.seek(2)
    risks = run_frame(c)
    for zid, r in risks.items():
        assert r.level == "NORMAL", f"{zid} should be calm at step 2"


def test_langtang_blindspot_appears_after_collapse():
    """THE headline claim: dual-channel alerts, rainfall-only does not."""
    c = ReplayCursor(); c.select("langtang-2026"); c.seek(11)
    risks = run_frame(c)

    blind = [r for r in risks.values() if r.blindspot]
    assert len(blind) >= 4, "the Trishuli corridor must flag as a blind spot"

    head = risks["np-langtang-head"]
    assert LEVEL_RANK[head.level] >= LEVEL_RANK["WARNING"]
    assert head.legacy_level == "NORMAL", "rainfall-only sees nothing at the source"

    exposed = sum(r.population for r in blind)
    assert exposed > 1_000_000, "the unwarned population is the headline number"


def test_langtang_stays_dry_throughout():
    """If rain crept into this scenario the whole argument would be circular."""
    c = ReplayCursor(); c.select("langtang-2026")
    for step in range(0, 30, 3):
        c.seek(step)
        for zid, w in c.frame()["weather"].items():
            if zid.startswith("np-"):
                assert w["rain_24h_mm"] < 5, f"{zid} must stay dry at step {step}"


def test_legacy_engine_misses_langtang_entirely():
    c = ReplayCursor(); c.select("langtang-2026"); c.seek(11)
    risks = run_frame(c, engine_mode="legacy")
    assert all(r.level == "NORMAL" for r in risks.values()), (
        "a rainfall-only engine must report the entire corridor as normal - "
        "this is the counterfactual the demo turns on"
    )


def test_assam_both_engines_agree():
    """The honesty check: on its home mechanism, legacy is not worse."""
    c = ReplayCursor(); c.select("assam-2026"); c.seek(18)
    dual = run_frame(c, "dual")
    legacy = run_frame(c, "legacy")
    for zid in dual:
        assert abs(dual[zid].score - legacy[zid].score) < 0.5
    assert not any(r.blindspot for r in dual.values())


def test_assam_escalates_downstream_in_order():
    c = ReplayCursor(); c.select("assam-2026"); c.seek(14)
    r = run_frame(c)
    assert r["in-sivasagar"].score >= r["in-golaghat"].score, (
        "the upstream tributary must load before the downstream reach"
    )


def test_analogue_retrieval_picks_the_right_mechanism():
    c = ReplayCursor(); c.select("langtang-2026"); c.seek(11)
    now = datetime.now(timezone.utc)
    frame = c.frame(now)
    head = next(z for z in zones() if z.id == "np-langtang-head")
    h = score_hydro(head, frame["weather"].get(head.id), frame["discharge"].get(head.id))
    g = score_geo(head, frame["seismic"], now)
    got = {a.incident_id for a in find_analogues(head, h, g, top_k=3)}
    assert {"chamoli-2021", "seti-2012"} & got, (
        "a dry seismic signature must retrieve the ice-rock avalanche cases, "
        f"got {got}"
    )
