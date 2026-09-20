"""USGS seismic adapter - Channel B's live input.

Deliberately queried at a LOW magnitude floor (M1.0) over a regional bounding
box rather than using the global all_hour feed. The reason is the whole point
of the project: a 0.2 km2 ice-rock collapse registers as a shallow, low-
magnitude, non-tectonic seismic signal. A monitoring system filtering at the
usual M4.5 "newsworthy earthquake" threshold discards exactly the event class
that killed people in the Trishuli valley. We keep the small ones and classify
them instead of dropping them.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import settings
from ..zones import Zone, haversine_km
from .base import Source

# Bounding box covering the Nepal Himalaya and the upper Brahmaputra valley.
REGION = {"minlatitude": 24.0, "maxlatitude": 31.0, "minlongitude": 82.0, "maxlongitude": 97.0}


class SeismicSource(Source):
    def __init__(self) -> None:
        super().__init__(name="usgs/fdsnws-event", ttl_s=settings.seismic_refresh_s)

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        key = "region"
        if self.fresh(key):
            return self.cached(key) or []

        start = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        params = {
            "format": "geojson",
            "starttime": start,
            "minmagnitude": 1.0,
            "orderby": "time",
            "limit": 200,
            **REGION,
        }
        raw = await self.get_json(client, settings.usgs_query_url, params)
        if raw is None:
            # Fall back to the global hourly summary; it needs no time params
            # and is served from a CDN, so it survives outages the query API
            # does not.
            raw = await self.get_json(client, settings.usgs_feed_url)
        if raw is None:
            return self.cached(key) or []

        events = [_normalise(f) for f in raw.get("features", [])]
        events = [e for e in events if e is not None]
        self.store(key, events)
        return events  # type: ignore[return-value]


def _normalise(feature: dict[str, Any]) -> dict[str, Any] | None:
    props = feature.get("properties") or {}
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") or []
    if len(coords) < 3 or props.get("mag") is None:
        return None
    lon, lat, depth = coords[0], coords[1], coords[2]
    ts = props.get("time")
    when = (
        datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat()
        if ts
        else datetime.now(timezone.utc).isoformat()
    )
    return {
        "id": feature.get("id", ""),
        "magnitude": float(props["mag"]),
        "mag_type": props.get("magType") or "",
        "depth_km": float(depth if depth is not None else 10.0),
        "lat": float(lat),
        "lon": float(lon),
        "place": props.get("place") or "",
        "time": when,
        "type": props.get("type") or "earthquake",
        "felt": props.get("felt"),
        "url": props.get("url") or "",
    }


def events_near(
    events: list[dict[str, Any]], zone: Zone, radius_km: float
) -> list[dict[str, Any]]:
    """Events within `radius_km` of a zone, nearest first, distance attached."""
    near = []
    for ev in events:
        dist = haversine_km(zone.lat, zone.lon, ev["lat"], ev["lon"])
        if dist <= radius_km:
            enriched = dict(ev)
            enriched["distance_km"] = round(dist, 1)
            near.append(enriched)
    return sorted(near, key=lambda e: e["distance_km"])
