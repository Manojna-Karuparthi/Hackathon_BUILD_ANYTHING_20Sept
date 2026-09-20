"""Multi-hazard taxonomy.

One vocabulary shared by every feed, the engine, the map and the translations.
Global feeds each use their own category names; they are all normalised into
these kinds on the way in, so the UI never has to know which source an event
came from.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HazardKind:
    id: str
    label: str
    glyph: str           # paired with the label everywhere - never colour alone
    family: str          # geophysical | hydrological | meteorological | climatological
    palette: str         # CSS token suffix
    onset: str           # how much warning the mechanism physically allows
    description: str


HAZARDS: tuple[HazardKind, ...] = (
    HazardKind("earthquake", "Earthquake", "◈", "geophysical", "quake", "seconds",
               "Ground rupture. No warning is possible before it starts; the warning is the "
               "seconds between detection and shaking arriving."),
    HazardKind("landslide", "Landslide", "◤", "geophysical", "slide", "minutes",
               "Slope failure, usually rainfall- or seismically-triggered."),
    HazardKind("glof", "Glacial lake outburst", "❄", "geophysical", "glof", "minutes",
               "Ice or moraine dam failure releasing an impounded lake. Often no rainfall "
               "precursor at all."),
    HazardKind("volcano", "Volcanic activity", "▲", "geophysical", "volcano", "hours",
               "Eruption, ashfall or lahar."),
    HazardKind("flood", "Flood", "≋", "hydrological", "flood", "hours",
               "River or surface flooding from rainfall and elevated discharge."),
    HazardKind("cyclone", "Cyclone / severe storm", "◉", "meteorological", "cyclone", "days",
               "Tropical cyclone or severe convective storm: wind, surge and rainfall together."),
    HazardKind("wildfire", "Wildfire", "▮", "meteorological", "fire", "hours",
               "Active fire, or fire weather from heat, low humidity and wind."),
    HazardKind("heatwave", "Extreme heat", "☀", "meteorological", "heat", "days",
               "Sustained temperature extremes. The deadliest hazard here by annual toll, "
               "and the least alarmed-on."),
    HazardKind("drought", "Drought", "◌", "climatological", "drought", "months",
               "Prolonged rainfall deficit."),
    HazardKind("other", "Other hazard", "●", "other", "other", "varies",
               "Catalogued event outside the categories above."),
)

HAZARD_INDEX = {h.id: h for h in HAZARDS}

# --- feed category mappings ------------------------------------------------
# NASA EONET v3 category ids
EONET_MAP = {
    "drought": "drought",
    "dustHaze": "other",
    "earthquakes": "earthquake",
    "floods": "flood",
    "landslides": "landslide",
    "manmade": "other",
    "seaLakeIce": "other",
    "severeStorms": "cyclone",
    "snow": "other",
    "tempExtremes": "heatwave",
    "volcanoes": "volcano",
    "waterColor": "other",
    "wildfires": "wildfire",
}

# GDACS event type codes
GDACS_MAP = {
    "EQ": "earthquake",
    "TC": "cyclone",
    "FL": "flood",
    "VO": "volcano",
    "DR": "drought",
    "WF": "wildfire",
}

# GDACS alert levels → our 0-100 severity scale
GDACS_SEVERITY = {"Green": 30.0, "Orange": 65.0, "Red": 90.0}


def kind(hazard_id: str) -> HazardKind:
    return HAZARD_INDEX.get(hazard_id, HAZARD_INDEX["other"])


def catalogue() -> list[dict]:
    return [
        {
            "id": h.id, "label": h.label, "glyph": h.glyph, "family": h.family,
            "palette": h.palette, "onset": h.onset, "description": h.description,
        }
        for h in HAZARDS
    ]
