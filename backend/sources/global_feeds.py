"""Global multi-hazard feeds.

Two free, key-less, worldwide sources, normalised into one event stream:

- NASA EONET v3 - curated natural event tracker (wildfires, storms, volcanoes,
  floods, landslides, ice, temperature extremes). Good coverage, no severity.
- GDACS - the UN/EC Global Disaster Alert and Coordination System. Fewer
  events, but each carries an official Green/Orange/Red alert level and a
  population-exposure estimate, which is what makes it worth joining.

Both go through the same circuit breaker as everything else, and both degrade
to a bundled snapshot rather than an empty map.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import DATA_DIR, settings
from ..hazards import EONET_MAP, GDACS_MAP, GDACS_SEVERITY
from .base import Source

EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"


def _snapshot(name: str) -> list[dict[str, Any]]:
    """Bundled offline snapshot, so the world map is never blank."""
    path = DATA_DIR / "snapshots" / f"{name}.json"
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("events", [])
    except (OSError, json.JSONDecodeError):
        return []


class EonetSource(Source):
    def __init__(self) -> None:
        super().__init__(name="nasa/eonet", ttl_s=600.0)

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        key = "open"
        if self.fresh(key):
            return self.cached(key) or []

        raw = await self.get_json(
            client, EONET_URL, {"status": "open", "limit": 150, "days": 30}
        )
        if raw is None:
            cached = self.cached(key)
            if cached:
                return cached
            self.mark_replay()
            return _snapshot("eonet")

        events = []
        for ev in raw.get("events", []):
            norm = _from_eonet(ev)
            if norm:
                events.append(norm)
        self.store(key, events)
        return events


class GdacsSource(Source):
    def __init__(self) -> None:
        super().__init__(name="gdacs/alerts", ttl_s=900.0)

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        key = "current"
        if self.fresh(key):
            return self.cached(key) or []

        raw = await self.get_json(client, GDACS_URL, {"pagesize": 100, "pagenumber": 1})
        if raw is None:
            cached = self.cached(key)
            if cached:
                return cached
            self.mark_replay()
            return _snapshot("gdacs")

        features = raw.get("features", raw if isinstance(raw, list) else [])
        events = []
        for f in features:
            norm = _from_gdacs(f)
            if norm:
                events.append(norm)
        self.store(key, events)
        return events


# --------------------------------------------------------------- normalisers
def _from_eonet(ev: dict[str, Any]) -> dict[str, Any] | None:
    cats = ev.get("categories") or []
    cat_id = cats[0].get("id") if cats else None
    geoms = ev.get("geometry") or []
    if not geoms:
        return None
    last = geoms[-1]
    coords = last.get("coordinates")
    if not coords:
        return None
    # Polygon geometries arrive nested; take the first vertex as a locator.
    while isinstance(coords[0], list):
        coords = coords[0]
    try:
        lon, lat = float(coords[0]), float(coords[1])
    except (TypeError, ValueError, IndexError):
        return None

    magnitude = last.get("magnitudeValue")
    unit = last.get("magnitudeUnit") or ""
    return {
        "id": f"eonet:{ev.get('id')}",
        "source": "NASA EONET",
        "hazard": EONET_MAP.get(str(cat_id), "other"),
        "title": ev.get("title") or "Unnamed event",
        "lat": lat, "lon": lon,
        "time": last.get("date") or datetime.now(timezone.utc).isoformat(),
        "severity": None,           # EONET does not rate severity
        "alert_level": None,
        "magnitude": float(magnitude) if magnitude is not None else None,
        "magnitude_unit": unit,
        "population_exposed": None,
        "url": (ev.get("sources") or [{}])[0].get("url", "") or ev.get("link", ""),
        "description": ev.get("description") or "",
    }


def _from_gdacs(feature: dict[str, Any]) -> dict[str, Any] | None:
    props = feature.get("properties", feature) or {}
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") or []
    if len(coords) >= 2:
        lon, lat = float(coords[0]), float(coords[1])
    else:
        try:
            lat = float(props.get("latitude"))
            lon = float(props.get("longitude"))
        except (TypeError, ValueError):
            return None

    etype = str(props.get("eventtype") or "").upper()
    alert = str(props.get("alertlevel") or "").capitalize()
    sev = props.get("severitydata") or {}

    return {
        "id": f"gdacs:{props.get('eventid')}-{props.get('episodeid', 0)}",
        "source": "GDACS",
        "hazard": GDACS_MAP.get(etype, "other"),
        "title": props.get("name") or props.get("htmldescription") or f"{etype} event",
        "lat": lat, "lon": lon,
        "time": props.get("fromdate") or datetime.now(timezone.utc).isoformat(),
        "severity": GDACS_SEVERITY.get(alert),
        "alert_level": alert or None,
        "magnitude": sev.get("severity"),
        "magnitude_unit": sev.get("severityunit") or "",
        "population_exposed": props.get("affectedcountries") and None,
        "url": props.get("url", {}).get("report") if isinstance(props.get("url"), dict) else "",
        "description": props.get("htmldescription") or "",
    }


def seismic_as_events(seismic: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold the USGS catalogue into the same global event shape.

    Kept separate from the regional Channel B scoring: the same earthquake is
    both a scored input for a watched zone and a pin on the world map, and it
    should not have to be fetched twice.
    """
    out = []
    for ev in seismic:
        mag = ev.get("magnitude")
        if mag is None:
            continue
        # Map magnitude onto the 0-100 severity scale. M7+ tops out.
        severity = max(0.0, min(100.0, (float(mag) - 2.0) / 5.0 * 100.0))
        out.append({
            "id": f"usgs:{ev.get('id')}",
            "source": "USGS",
            "hazard": "earthquake",
            "title": f"M{mag:.1f} - {ev.get('place') or 'unknown location'}",
            "lat": ev["lat"], "lon": ev["lon"],
            "time": ev.get("time"),
            "severity": round(severity, 1),
            "alert_level": ("Red" if mag >= 6.0 else "Orange" if mag >= 4.5 else "Green"),
            "magnitude": float(mag),
            "magnitude_unit": "M",
            "population_exposed": None,
            "url": ev.get("url", ""),
            "description": f"Depth {ev.get('depth_km', 0):.1f} km",
        })
    return out


def recent_only(events: list[dict[str, Any]], days: int = 30) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    keep = []
    for ev in events:
        try:
            t = datetime.fromisoformat(str(ev["time"]).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
        except (ValueError, KeyError, TypeError):
            keep.append(ev)
            continue
        if t >= cutoff:
            keep.append(ev)
    return keep
