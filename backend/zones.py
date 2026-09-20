"""Zone + basin registry, loaded once from data/zones.json."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from .config import DATA_DIR


@dataclass(frozen=True)
class Reach:
    src: str
    dst: str
    distance_km: float
    velocity_ms: float
    gradient: str


@dataclass(frozen=True)
class Basin:
    id: str
    name: str
    country: str
    head_zone: str
    description: str
    reaches: tuple[Reach, ...]


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    admin: str
    country: str
    lat: float
    lon: float
    elevation_m: float
    population: int
    basin: str
    river: str
    channel_position_km: float
    terrain: str
    terrain_factor: float
    vulnerability: float
    geo_watch: bool
    wards: tuple[str, ...]
    notes: str
    cryosphere: dict[str, Any] = field(default_factory=dict)

    @property
    def rain_24h_threshold(self) -> float:
        """IMD 'very heavy' (115.6mm/24h) scaled by terrain.

        A steep glacial catchment converts far less rain into a destructive
        discharge than a flat alluvial plain, so its threshold sits lower.
        """
        return 115.6 * self.terrain_factor

    @property
    def rain_1h_threshold(self) -> float:
        """Short-duration cloudburst threshold. IMD treats >=50mm/h as a
        cloudburst; scaled the same way."""
        return 50.0 * self.terrain_factor


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    with open(DATA_DIR / "zones.json", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def zones() -> tuple[Zone, ...]:
    out = []
    for z in _raw()["zones"]:
        out.append(
            Zone(
                id=z["id"], name=z["name"], admin=z["admin"], country=z["country"],
                lat=z["lat"], lon=z["lon"], elevation_m=z["elevation_m"],
                population=z["population"], basin=z["basin"], river=z["river"],
                channel_position_km=z["channel_position_km"], terrain=z["terrain"],
                terrain_factor=z["terrain_factor"], vulnerability=z["vulnerability"],
                geo_watch=z["geo_watch"], wards=tuple(z.get("wards", [])),
                notes=z.get("notes", ""), cryosphere=z.get("cryosphere", {}),
            )
        )
    return tuple(out)


@lru_cache(maxsize=1)
def basins() -> tuple[Basin, ...]:
    out = []
    for b in _raw()["basins"]:
        reaches = tuple(
            Reach(r["from"], r["to"], r["distance_km"], r["debris_velocity_ms"], r["gradient"])
            for r in b["reaches"]
        )
        out.append(
            Basin(b["id"], b["name"], b["country"], b["head_zone"], b["description"], reaches)
        )
    return tuple(out)


@lru_cache(maxsize=1)
def zone_index() -> dict[str, Zone]:
    return {z.id: z for z in zones()}


def get_zone(zone_id: str) -> Zone | None:
    return zone_index().get(zone_id)


@lru_cache(maxsize=1)
def downstream_paths() -> dict[str, list[tuple[str, float, float, list[str]]]]:
    """For each zone, every zone below it: (zone_id, cumulative_km, eta_s, path).

    Travel time is summed per reach because a debris flood decelerates as the
    valley flattens; a single basin-wide velocity would badly misstate arrival
    in the lower reaches.
    """
    graph: dict[str, list[Reach]] = {}
    for b in basins():
        for r in b.reaches:
            graph.setdefault(r.src, []).append(r)

    result: dict[str, list[tuple[str, float, float, list[str]]]] = {}
    for zone in zones():
        acc: list[tuple[str, float, float, list[str]]] = []
        stack = [(zone.id, 0.0, 0.0, [zone.id])]
        while stack:
            node, km, secs, path = stack.pop()
            for reach in graph.get(node, []):
                nkm = km + reach.distance_km
                nsecs = secs + (reach.distance_km * 1000.0) / max(reach.velocity_ms, 0.1)
                npath = path + [reach.dst]
                acc.append((reach.dst, nkm, nsecs, npath))
                stack.append((reach.dst, nkm, nsecs, npath))
        result[zone.id] = sorted(acc, key=lambda t: t[2])
    return result
