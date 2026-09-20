"""API contract tests. Boots the real app with the real lifespan."""
import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_reports_every_subsystem(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    assert len(h["sources"]) == 3
    assert h["corpus"]["incidents"] >= 10
    assert "browser-siren" in h["channels"]


def test_state_has_every_zone(client):
    s = client.get("/api/state").json()
    assert len(s["zones"]) == 10
    for z in s["zones"]:
        assert 0 <= z["score"] <= 100
        assert z["level"] in {"NORMAL", "ADVISORY", "WATCH", "WARNING", "EMERGENCY"}
        assert z["explanation"], "every zone must be able to explain itself"


def test_methodology_is_served_as_data(client):
    m = client.get("/api/methodology").json()
    assert m["fusion"]["formula"].startswith("R = max")
    assert sum(m["hydro"]["weights"].values()) == pytest.approx(1.0)
    assert sum(m["geo"]["weights"].values()) == pytest.approx(1.0)


def test_scenario_switch_and_seek(client):
    assert client.post("/api/scenario/langtang-2026").json()["ok"]
    assert client.post("/api/playback/seek?step=11").json()["step"] == 11
    s = client.get("/api/state").json()
    assert s["scenario"] == "langtang-2026"
    assert s["blindspot_zones"], "step 11 must expose blind spots"


def test_unknown_scenario_is_rejected(client):
    assert client.post("/api/scenario/nope").status_code == 404


def test_engine_toggle_changes_the_verdict(client):
    client.post("/api/scenario/langtang-2026")
    client.post("/api/playback/seek?step=11")

    client.post("/api/engine/dual")
    dual = client.get("/api/state").json()

    client.post("/api/engine/legacy")
    legacy = client.get("/api/state").json()

    assert dual["population_at_risk"] > 0
    assert legacy["population_at_risk"] == 0, (
        "legacy must report nobody at risk while the surge is moving"
    )
    client.post("/api/engine/dual")


def test_bad_engine_mode_rejected(client):
    assert client.post("/api/engine/quantum").status_code == 400


def test_drill_fires_the_pipeline(client):
    rec = client.post("/api/simulate/np-rasuwa?level=EMERGENCY").json()
    assert rec["level"] == "EMERGENCY"
    assert rec["simulated"] is True
    assert "browser-siren" in rec["dispatched"]
    assert rec["spoken"], "a drill must produce speakable text"
    assert client.get("/api/alerts").json()["alerts"], "the drill must be logged"


def test_drill_on_unknown_zone_404s(client):
    assert client.post("/api/simulate/atlantis").status_code == 404


def test_websocket_pushes_state(client):
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "state"
        assert len(msg["payload"]["zones"]) == 10
