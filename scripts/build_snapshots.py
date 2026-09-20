"""Generate offline snapshots for the global hazard feeds.

These are the map's fallback when NASA EONET and GDACS are unreachable. They
are clearly marked as snapshots in the API and in the UI - a world map that
silently shows month-old pins as if they were live would be exactly the kind
of dishonesty this project is arguing against.

Regenerate from real feeds when you have network:
    python scripts/build_snapshots.py --live
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "snapshots"
OUT.mkdir(parents=True, exist_ok=True)

NOW = datetime.now(timezone.utc)


def ago(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat()


# A geographically spread, hazard-diverse set so the world map demonstrates the
# categorisation properly offline. Locations are real; these are representative
# placeholders, not claims about specific current events.
EONET = [
    ("wildfire",  "Wildfire - Northern California",        40.55, -122.40,  6,  None),
    ("wildfire",  "Wildfire - Central Portugal",           39.90,   -8.10, 14,  None),
    ("wildfire",  "Bushfire - New South Wales",           -33.10,  150.20, 26,  None),
    ("volcano",   "Volcanic activity - Mount Etna",        37.75,   14.99, 10,  None),
    ("volcano",   "Volcanic activity - Sakurajima",        31.59,  130.66, 30,  None),
    ("volcano",   "Volcanic activity - Popocatepetl",      19.02,  -98.62, 18,  None),
    ("cyclone",   "Severe storm - Western Pacific",        18.40,  132.70,  4,  None),
    ("cyclone",   "Severe storm - Gulf of Mexico",         25.10,  -90.30, 12,  None),
    ("flood",     "Flooding - Lower Mekong",               12.60,  105.80, 22,  None),
    ("flood",     "Flooding - Rio Parana basin",          -27.40,  -58.90, 40,  None),
    ("landslide", "Landslide - Central Java",              -7.30,  110.10, 16,  None),
    ("heatwave",  "Temperature extreme - Sahel",           15.30,    2.10, 34,  None),
    ("drought",   "Drought - Horn of Africa",               6.20,   42.10, 90,  None),
    ("other",     "Sea and lake ice - Barents Sea",        74.50,   38.00, 50,  None),
]

GDACS = [
    ("earthquake", "M6.1 earthquake - offshore Honshu",     38.30, 142.60, "Orange",  2, 6.1, "M"),
    ("earthquake", "M5.4 earthquake - central Chile",      -33.40, -70.80, "Green",   9, 5.4, "M"),
    ("cyclone",    "Tropical cyclone - Bay of Bengal",      16.80,  88.40, "Red",     5, 165, "km/h"),
    ("cyclone",    "Tropical cyclone - Coral Sea",         -16.20, 152.30, "Orange", 20, 120, "km/h"),
    ("flood",      "Flood - Brahmaputra basin",             26.40,  92.10, "Orange", 11, None, ""),
    ("flood",      "Flood - Niger delta",                    5.40,   6.30, "Green",  28, None, ""),
    ("wildfire",   "Wildfire - Iberian peninsula",          40.20,  -5.60, "Orange", 15, None, ""),
    ("volcano",    "Volcanic eruption - Sunda arc",         -8.10, 114.20, "Orange", 24, None, ""),
    ("drought",    "Drought - southern Africa",            -22.40,  25.10, "Red",   200, None, ""),
]


def build_eonet() -> dict:
    return {
        "snapshot": True,
        "generated_at": NOW.isoformat(),
        "note": "Offline fallback for NASA EONET. Representative placeholders, not live data.",
        "events": [
            {
                "id": f"eonet:snap-{i}", "source": "NASA EONET (snapshot)", "hazard": hz,
                "title": title, "lat": lat, "lon": lon, "time": ago(hrs),
                "severity": None, "alert_level": None, "magnitude": mag,
                "magnitude_unit": "", "population_exposed": None, "url": "",
                "description": "Bundled offline snapshot.",
            }
            for i, (hz, title, lat, lon, hrs, mag) in enumerate(EONET)
        ],
    }


def build_gdacs() -> dict:
    from backend.hazards import GDACS_SEVERITY

    return {
        "snapshot": True,
        "generated_at": NOW.isoformat(),
        "note": "Offline fallback for GDACS. Representative placeholders, not live data.",
        "events": [
            {
                "id": f"gdacs:snap-{i}", "source": "GDACS (snapshot)", "hazard": hz,
                "title": title, "lat": lat, "lon": lon, "time": ago(hrs),
                "severity": GDACS_SEVERITY.get(alert), "alert_level": alert,
                "magnitude": mag, "magnitude_unit": unit, "population_exposed": None,
                "url": "", "description": "Bundled offline snapshot.",
            }
            for i, (hz, title, lat, lon, alert, hrs, mag, unit) in enumerate(GDACS)
        ],
    }


async def live() -> None:
    import httpx
    from backend.sources.global_feeds import EonetSource, GdacsSource

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for src, name in ((EonetSource(), "eonet"), (GdacsSource(), "gdacs")):
            events = await src.fetch(client)
            if not events:
                print(f"{name}: no events returned, keeping existing snapshot")
                continue
            (OUT / f"{name}.json").write_text(
                json.dumps(
                    {"snapshot": True, "generated_at": NOW.isoformat(),
                     "note": f"Captured from the live {name} feed.", "events": events},
                    indent=1,
                ),
                encoding="utf-8",
            )
            print(f"{name}: captured {len(events)} live events")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="capture from the real feeds")
    args = ap.parse_args()

    if args.live:
        import asyncio
        asyncio.run(live())
        return

    for name, data in (("eonet", build_eonet()), ("gdacs", build_gdacs())):
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        print(f"wrote data/snapshots/{name}.json ({len(data['events'])} events)")


if __name__ == "__main__":
    main()
