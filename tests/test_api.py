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
    names = {s["name"] for s in h["sources"]}
    assert {"open-meteo/forecast", "open-meteo/glofas-flood", "usgs/fdsnws-event",
            "nasa/eonet", "gdacs/alerts"} <= names
    assert h["corpus"]["incidents"] >= 10
    assert "browser-siren" in h["channels"]
    assert h["languages"]["languages"] >= 10


def test_messaging_app_channel_is_gone(client):
    """WhatsApp delivery was removed: it made the most visible channel depend
    on a third-party sandbox and a pre-registered number."""
    channels = client.get("/api/health").json()["channels"]
    assert "whatsapp" not in channels
    assert set(channels) == {"browser-siren", "speech-synthesis", "alert-log", "webhook"}


def test_hazard_catalogue_and_global_events(client):
    cat = client.get("/api/hazards").json()["hazards"]
    assert len(cat) >= 9 and all(h["glyph"] for h in cat)
    g = client.get("/api/global-events").json()
    assert g["count"] > 0, "the world map must never be empty, even offline"
    kinds = {h["id"] for h in cat}
    assert all(e["hazard"] in kinds for e in g["events"])


def test_global_events_filter_by_hazard(client):
    only = client.get("/api/global-events?hazard=wildfire,flood").json()
    assert only["count"] > 0
    assert {e["hazard"] for e in only["events"]} <= {"wildfire", "flood"}


def test_forecasts_endpoint_declares_its_methods(client):
    f = client.get("/api/forecasts").json()
    assert f["alarm_threshold"] > 0
    for row in f["forecasts"]:
        assert row["method"], "every probability must name the method behind it"
        assert row["basis"], "every probability must show its working"
        assert 0.0 <= row["probability"] <= 1.0


def test_language_endpoints(client):
    langs = client.get("/api/languages").json()
    assert len(langs["languages"]) >= 10
    assert any(l["dialect_of"] for l in langs["languages"])
    assert langs["review"]["status"] == "UNREVIEWED_MACHINE_ASSISTED"
    assert client.post("/api/language/ne").json()["ok"]
    assert client.post("/api/language/klingon").status_code == 404
    client.post("/api/language/en")


def test_assistant_answers_in_requested_language(client):
    en = client.post("/api/assistant", json={"question": "what should I do", "lang": "en"}).json()
    ne = client.post("/api/assistant", json={"question": "what should I do", "lang": "ne"}).json()
    assert en["speak"] and ne["speak"]
    assert ne["speak"] != en["speak"], "the Nepali answer must actually be Nepali"
    assert ne["speech_lang"].startswith("ne")
    assert en["source"] in {"rules", "hf-inference"}


def test_assistant_intents(client):
    for q, intent in [
        ("what is happening", "status"), ("am i safe", "safety"),
        ("what should i do", "action"), ("when will it arrive", "eta"),
        ("why", "why"), ("what is the forecast", "forecast"),
        ("show global hazards", "hazards"),
    ]:
        got = client.post("/api/assistant", json={"question": q, "lang": "en", "allow_llm": False}).json()
        assert got["intent"] == intent, f"{q!r} -> {got['intent']}, expected {intent}"
        assert got["text"]


def test_alerts_carry_translations(client):
    """An alert ships with every translation, so a PA or SMS integration
    downstream never needs a second round trip to speak to its own community."""
    client.post("/api/simulate/np-rasuwa?level=EMERGENCY")
    alert = client.get("/api/alerts?limit=1").json()["alerts"][0]
    assert alert["trigger"] in {"conditions", "forecast", "drill"}
    assert len(alert["translations"]) >= 10
    assert alert["translations"]["ne"] != alert["translations"]["en"]


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
