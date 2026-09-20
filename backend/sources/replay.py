"""Scenario replay source.

Serves a recorded frame in the exact shape the live adapters return, so the
engine cannot tell the difference. Two jobs:

1. Rehearsal. Judges cannot wait for a real glacier to fail, and the whole
   point of the system is an event that happens once a decade.
2. Survival. Conference wifi fails. A warning system that cannot demonstrate
   itself offline has not earned anyone's trust.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from ..config import DATA_DIR
from ..models import ScenarioInfo

SCENARIO_DIR = DATA_DIR / "scenarios"


@lru_cache(maxsize=8)
def load_scenario(scenario_id: str) -> dict[str, Any] | None:
    path = SCENARIO_DIR / f"{scenario_id}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def list_scenarios() -> list[ScenarioInfo]:
    out = [
        ScenarioInfo(
            id="live",
            label="Live feeds",
            subtitle="Open-Meteo + GloFAS + USGS, right now",
            mechanism="Whatever is actually happening",
            duration_steps=0,
            is_live=True,
            teaches="Real current conditions across all ten monitored zones.",
        )
    ]
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        data = load_scenario(path.stem)
        if not data:
            continue
        out.append(
            ScenarioInfo(
                id=data["id"], label=data["label"], subtitle=data["subtitle"],
                mechanism=data["mechanism"], duration_steps=len(data["steps"]),
                is_live=False, teaches=data["teaches"],
            )
        )
    return out


class ReplayCursor:
    """Tracks position within a scenario and materialises the current frame."""

    def __init__(self) -> None:
        self.scenario_id: str = "live"
        self.step: int = 0
        self.playing: bool = False

    def select(self, scenario_id: str) -> bool:
        if scenario_id != "live" and load_scenario(scenario_id) is None:
            return False
        self.scenario_id = scenario_id
        self.step = 0
        self.playing = scenario_id != "live"
        return True

    @property
    def is_live(self) -> bool:
        return self.scenario_id == "live"

    def scenario(self) -> dict[str, Any] | None:
        return None if self.is_live else load_scenario(self.scenario_id)

    def total_steps(self) -> int:
        sc = self.scenario()
        return len(sc["steps"]) if sc else 0

    def advance(self) -> None:
        sc = self.scenario()
        if not sc or not self.playing:
            return
        if self.step < len(sc["steps"]) - 1:
            self.step += 1
        else:
            self.playing = False  # hold on the final frame rather than looping

    def seek(self, step: int) -> None:
        total = self.total_steps()
        if total:
            self.step = max(0, min(step, total - 1))

    def frame(self, now: datetime | None = None) -> dict[str, Any] | None:
        """Current frame, with relative event times resolved to absolute."""
        sc = self.scenario()
        if not sc:
            return None
        now = now or datetime.now(timezone.utc)
        raw = sc["steps"][self.step]

        weather, discharge = {}, {}
        for zone_id, w in raw["weather"].items():
            w = dict(w)
            ratio = w.pop("anomaly_ratio", None)
            weather[zone_id] = w
            if ratio is not None:
                base = 400.0
                discharge[zone_id] = {
                    "discharge_m3s": round(base * ratio, 1),
                    "baseline_m3s": base,
                    "anomaly_ratio": ratio,
                    "series": [],
                }

        seismic = []
        for ev in raw["seismic"]:
            ev = dict(ev)
            mins = ev.pop("minutes_ago", 0)
            ev["time"] = (now - timedelta(minutes=mins)).isoformat()
            ev.setdefault("felt", None)
            ev.setdefault("url", "")
            seismic.append(ev)

        return {
            "weather": weather,
            "discharge": discharge,
            "seismic": seismic,
            "narrative": raw["narrative"],
            "index": raw["index"],
            "total": len(sc["steps"]),
            "clock": (
                now.replace(second=0, microsecond=0) + timedelta(minutes=raw["clock_offset_min"])
            ).isoformat(),
            "label": sc["label"],
        }
