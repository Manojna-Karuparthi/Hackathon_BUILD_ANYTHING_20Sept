"""Wire schemas. These are the contract between engine, API and dashboard."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Level = Literal["NORMAL", "ADVISORY", "WATCH", "WARNING", "EMERGENCY"]


class Contribution(BaseModel):
    """One named term in a channel score, carried all the way to the UI.

    Every number a judge can see on screen can be traced back to one of these.
    """

    key: str
    label: str
    raw: float | None = None
    unit: str = ""
    normalised: float = Field(0.0, description="0-1 after threshold curve")
    weight: float = 0.0
    points: float = Field(0.0, description="normalised * weight * 100")
    detail: str = ""


class ChannelScore(BaseModel):
    channel: Literal["HYDRO", "GEO"]
    score: float = 0.0
    confidence: float = Field(1.0, description="0-1, degrades when inputs are stale")
    contributions: list[Contribution] = []
    inputs_stale: bool = False
    summary: str = ""


class CascadeAlert(BaseModel):
    """An upstream mass-movement signal propagated to a downstream zone."""

    source_zone_id: str
    source_zone_name: str
    distance_km: float
    velocity_ms: float
    eta_seconds: float
    eta_iso: str
    transferred_score: float
    source_score: float = Field(0.0, description="Undecayed score at the source zone")
    path: list[str] = []
    floored: bool = Field(False, description="Level raised by the confirmed-event floor")


class Analogue(BaseModel):
    incident_id: str
    title: str
    date: str
    similarity: float
    mechanism: str
    outcome: str
    lesson: str


class ZoneRisk(BaseModel):
    zone_id: str
    name: str
    admin: str
    country: str
    lat: float
    lon: float
    population: int
    wards: list[str] = []
    basin: str
    river: str

    score: float = 0.0
    level: Level = "NORMAL"
    legacy_score: float = Field(
        0.0, description="Rainfall-only score a single-channel system would produce"
    )
    legacy_level: Level = "NORMAL"
    blindspot: bool = Field(
        False, description="True when dual-channel fires but legacy stays quiet"
    )

    hydro: ChannelScore
    geo: ChannelScore
    fusion_note: str = ""
    cascade: CascadeAlert | None = None
    analogues: list[Analogue] = []
    explanation: str = ""
    explanation_source: Literal["rules", "hf-inference"] = "rules"
    updated_at: str


class AlertRecord(BaseModel):
    id: int | None = None
    zone_id: str
    zone_name: str
    level: Level
    previous_level: Level
    score: float
    channel: str
    headline: str
    body: str
    spoken: str
    cascade_eta_s: float | None = None
    created_at: str
    dispatched: list[str] = []
    simulated: bool = False


class SourceHealth(BaseModel):
    name: str
    mode: Literal["live", "replay", "cache", "down"]
    last_success: str | None = None
    last_error: str | None = None
    latency_ms: float | None = None
    consecutive_failures: int = 0
    calls: int = 0


class SystemState(BaseModel):
    generated_at: str
    scenario: str
    scenario_label: str
    clock: str
    source_mode: str
    engine_mode: Literal["dual", "legacy"]
    zones: list[ZoneRisk]
    sources: list[SourceHealth]
    national_level: Level
    population_at_risk: int
    blindspot_zones: list[str] = []
    seismic_events: list[dict[str, Any]] = []
    hf: dict[str, Any] = {}


class ScenarioInfo(BaseModel):
    id: str
    label: str
    subtitle: str
    mechanism: str
    duration_steps: int
    is_live: bool
    teaches: str
