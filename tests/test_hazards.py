"""Multi-hazard taxonomy and global feed normalisation."""
from backend.hazards import EONET_MAP, GDACS_MAP, catalogue, kind
from backend.sources.global_feeds import _from_eonet, _from_gdacs, recent_only, seismic_as_events


def test_catalogue_is_complete_and_glyphed():
    cat = catalogue()
    assert len(cat) >= 9
    for h in cat:
        assert h["glyph"], f"{h['id']} needs a glyph - colour alone is not enough"
        assert h["label"] and h["family"] and h["description"]


def test_every_feed_category_maps_to_a_known_kind():
    ids = {h["id"] for h in catalogue()}
    for mapped in list(EONET_MAP.values()) + list(GDACS_MAP.values()):
        assert mapped in ids


def test_unknown_kind_degrades_to_other():
    assert kind("meteor_strike").id == "other"


def test_eonet_normalisation():
    ev = _from_eonet({
        "id": "E1", "title": "Wildfire A", "categories": [{"id": "wildfires"}],
        "geometry": [{"coordinates": [-120.5, 38.2], "date": "2026-09-19T00:00:00Z"}],
        "sources": [{"url": "http://x"}],
    })
    assert ev["hazard"] == "wildfire" and ev["lat"] == 38.2 and ev["lon"] == -120.5


def test_eonet_handles_polygon_geometry():
    """Polygon events arrive with nested coordinate arrays."""
    ev = _from_eonet({
        "id": "E2", "title": "Storm", "categories": [{"id": "severeStorms"}],
        "geometry": [{"coordinates": [[[10.0, 20.0], [11.0, 21.0]]], "date": "2026-09-19T00:00:00Z"}],
    })
    assert ev is not None and ev["hazard"] == "cyclone"
    assert ev["lon"] == 10.0 and ev["lat"] == 20.0


def test_eonet_rejects_geometryless_event():
    assert _from_eonet({"id": "E3", "title": "x", "categories": [{"id": "floods"}], "geometry": []}) is None


def test_gdacs_alert_level_maps_to_severity():
    ev = _from_gdacs({
        "properties": {"eventid": 1, "eventtype": "TC", "alertlevel": "Red",
                       "name": "Cyclone X", "latitude": 16.8, "longitude": 88.4,
                       "fromdate": "2026-09-19T00:00:00"},
        "geometry": {"coordinates": [88.4, 16.8]},
    })
    assert ev["hazard"] == "cyclone" and ev["alert_level"] == "Red" and ev["severity"] == 90.0


def test_seismic_folds_into_global_events():
    evs = seismic_as_events([
        {"id": "a", "magnitude": 6.5, "lat": 1, "lon": 2, "place": "X", "time": "t", "depth_km": 10},
        {"id": "b", "magnitude": 3.0, "lat": 3, "lon": 4, "place": "Y", "time": "t", "depth_km": 5},
    ])
    assert [e["hazard"] for e in evs] == ["earthquake", "earthquake"]
    assert evs[0]["alert_level"] == "Red" and evs[1]["alert_level"] == "Green"
    assert evs[0]["severity"] > evs[1]["severity"]


def test_recent_only_keeps_undated_events():
    """A feed entry with an unparseable date is kept rather than silently
    dropped - losing a hazard because its timestamp was odd is the wrong
    failure direction."""
    kept = recent_only([{"time": "not-a-date", "hazard": "flood"}], days=1)
    assert len(kept) == 1
