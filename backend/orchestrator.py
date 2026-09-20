"""The tick loop: pull inputs, score every zone, decide alerts, fan out.

One pass through here produces one complete SystemState, which is what both
the REST snapshot and the WebSocket push serve. Keeping a single code path for
live and replay means the thing demonstrated on stage is the thing that runs.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .alerts.channels import dispatch_all
from .config import LEVEL_RANK, settings
from . import i18n
from .engine.analogue import find_analogues
from .engine.forecast import forecast_zone
from .engine.explain import build_explanation, build_headline, build_spoken
from .engine.fusion import build_zone_risk, compute_cascades
from .engine.geo import score_geo
from .engine.hydro import score_hydro
from .engine.state import AlertStateMachine
from .models import AlertRecord, ForecastOut, GlobalEvent, SystemState, ZoneRisk
from .sources.huggingface import HuggingFaceSource
from .sources.global_feeds import (
    EonetSource,
    GdacsSource,
    recent_only,
    seismic_as_events,
)
from .sources.openmeteo import DischargeSource, WeatherSource
from .sources.replay import ReplayCursor
from .sources.usgs import SeismicSource
from . import store
from .zones import zones


class Orchestrator:
    def __init__(self) -> None:
        self.weather = WeatherSource()
        self.discharge = DischargeSource()
        self.seismic = SeismicSource()
        self.eonet = EonetSource()
        self.gdacs = GdacsSource()
        self.hf = HuggingFaceSource()
        self.cursor = ReplayCursor()
        self.machine = AlertStateMachine()

        self.engine_mode: str = "dual"          # "dual" | "legacy"
        self.language: str = "en"               # alert + assistant language
        self.global_events: list[dict] = []
        self.state: SystemState | None = None
        self.narrative: str = ""
        self.subscribers: set[asyncio.Queue] = set()
        self.pending_alerts: list[AlertRecord] = []
        self._client: httpx.AsyncClient | None = None
        self._live_ok: bool | None = None
        self._fell_back: bool = False
        self._last_seismic: list[dict] = []
        self._global_tick: int = 0
        self._forecast_alarms: dict[str, float] = {}
        self._lock = asyncio.Lock()

    # --- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": "Prahari/1.0 (geohazard early warning demo)"},
            follow_redirects=True,
        )
        store.init_db()
        if settings.source_mode in {"replay", "demo"}:
            self.cursor.select("langtang-2026")
            self.cursor.playing = False

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()

    async def refresh_global(self) -> list[dict]:
        """Worldwide hazard events. Polled on its own slower cadence - these
        feeds update in hours, not seconds, and hammering them adds nothing."""
        if self._client is None:
            return self.global_events
        eonet, gdacs = await asyncio.gather(
            self.eonet.fetch(self._client),
            self.gdacs.fetch(self._client),
        )
        merged = list(eonet) + list(gdacs)
        merged += seismic_as_events(self._last_seismic)
        # De-duplicate: GDACS and USGS both carry the big earthquakes.
        seen: set[str] = set()
        unique = []
        for ev in recent_only(merged, days=30):
            key = f"{ev['hazard']}:{round(ev['lat'], 1)}:{round(ev['lon'], 1)}"
            if key in seen:
                continue
            seen.add(key)
            unique.append(ev)
        self.global_events = unique
        return unique

    # --- input acquisition ------------------------------------------------
    async def _gather_inputs(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)

        if not self.cursor.is_live:
            frame = self.cursor.frame(now)
            if frame:
                for src in (self.weather, self.discharge, self.seismic):
                    src.mark_replay()
                # Never let the scenario's own narrative hide the fact that we
                # are on replay because live was unreachable. A warning system
                # must not quietly look live when it is not.
                prefix = (
                    "LIVE FEEDS UNREACHABLE - showing recorded scenario frames, not "
                    "current readings. "
                    if self._fell_back
                    else ""
                )
                self.narrative = prefix + frame["narrative"]
                return {
                    "weather": frame["weather"], "discharge": frame["discharge"],
                    "seismic": frame["seismic"], "clock": frame["clock"], "now": now,
                }

        zs = list(zones())
        assert self._client is not None
        weather, discharge, seismic = await asyncio.gather(
            self.weather.fetch(self._client, zs),
            self.discharge.fetch(self._client, zs),
            self.seismic.fetch(self._client),
        )

        live_ok = bool(weather)
        if self._live_ok is None:
            self._live_ok = live_ok

        # AUTO mode: if live never came up, fall back to a replay so the
        # dashboard is never a wall of zeroes with no explanation.
        if not live_ok and settings.source_mode == "auto" and self.cursor.is_live:
            self.cursor.select("langtang-2026")
            self.cursor.playing = False
            self._fell_back = True
            return await self._gather_inputs()

        self.narrative = (
            "Live monitoring across 10 zones in Nepal and Assam."
            if live_ok
            else "Live feeds degraded; serving last cached readings."
        )
        return {
            "weather": weather, "discharge": discharge, "seismic": seismic,
            "clock": now.isoformat(), "now": now,
        }

    # --- one full pass ----------------------------------------------------
    async def tick(self, advance: bool = True) -> SystemState:
        async with self._lock:
            if advance and not self.cursor.is_live and self.cursor.playing:
                self.cursor.advance()

            inputs = await self._gather_inputs()
            now: datetime = inputs["now"]
            weather = inputs["weather"] or {}
            discharge = inputs["discharge"] or {}
            seismic = inputs["seismic"] or []

            # Pass 1: independent channel scores.
            hydro_scores, geo_scores, raw_geo = {}, {}, {}
            for zone in zones():
                h = score_hydro(zone, weather.get(zone.id), discharge.get(zone.id))
                g = score_geo(zone, seismic, now)
                hydro_scores[zone.id] = h
                geo_scores[zone.id] = g
                raw_geo[zone.id] = g.score

            self._last_seismic = seismic

            # Pass 2: propagate upstream mass movement downstream.
            cascades = compute_cascades(raw_geo, now)

            # Pass 3: fuse, explain, decide.
            risks: list[ZoneRisk] = []
            history_rows = []
            for zone in zones():
                risk = build_zone_risk(
                    zone, hydro_scores[zone.id], geo_scores[zone.id],
                    cascades.get(zone.id), now, self.engine_mode,
                )
                risk.analogues = find_analogues(zone, risk.hydro, risk.geo)

                # Forecast layer: what happens NEXT, with a probability and the
                # method that produced it.
                fcs = forecast_zone(
                    zone, weather.get(zone.id), risk.score, seismic,
                    settings.forecast_horizon_h,
                )
                risk.forecasts = [
                    ForecastOut(
                        hazard=f.hazard, horizon_hours=f.horizon_hours,
                        probability=f.probability, percent=round(f.probability * 100),
                        band=f.band, method=f.method, basis=f.basis,
                        actionable=f.actionable, expected_value=f.expected_value,
                        expected_unit=f.expected_unit,
                    )
                    for f in fcs
                ]
                risk.top_probability = round(max((f.probability for f in fcs), default=0.0), 4)
                risk.forecast_alarm = any(f.actionable for f in fcs)

                risk.explanation = build_explanation(risk)
                risks.append(risk)
                history_rows.append((
                    zone.id, risk.score, risk.legacy_score,
                    risk.hydro.score, risk.geo.score, risk.level,
                ))

            store.record_scores(history_rows, self.cursor.scenario_id)

            # Pass 4: alert state machine + fan-out.
            for risk in risks:
                decision = self.machine.evaluate(risk.zone_id, risk.score)
                risk.level = decision.level  # machine output is authoritative
                if decision.should_notify:
                    await self._raise_alert(
                        risk, simulated=not self.cursor.is_live, trigger="conditions"
                    )
                elif risk.forecast_alarm and self._forecast_alarm_due(risk):
                    # A high-probability forecast raises an alarm BEFORE current
                    # conditions cross a threshold. This is the whole point of
                    # the prediction layer: waiting for the threshold means
                    # warning people while the water is already arriving.
                    await self._raise_alert(
                        risk, simulated=not self.cursor.is_live, trigger="forecast"
                    )

            national = max(
                (r.level for r in risks), key=lambda lv: LEVEL_RANK[lv], default="NORMAL"
            )
            at_risk = sum(
                r.population for r in risks if LEVEL_RANK[r.level] >= LEVEL_RANK["WATCH"]
            )

            # Global feeds run on a slower cadence than the zone engine.
            self._global_tick += 1
            if self._global_tick % 15 == 1 or not self.global_events:
                try:
                    await self.refresh_global()
                except Exception:  # noqa: BLE001
                    pass

            hazard_counts: dict[str, int] = {}
            for ev in self.global_events:
                hazard_counts[ev["hazard"]] = hazard_counts.get(ev["hazard"], 0) + 1

            state = SystemState(
                generated_at=now.isoformat(),
                scenario=self.cursor.scenario_id,
                scenario_label=(
                    "Live feeds" if self.cursor.is_live
                    else (self.cursor.scenario() or {}).get("label", self.cursor.scenario_id)
                ),
                clock=inputs["clock"],
                source_mode="live" if self.cursor.is_live else "replay",
                engine_mode=self.engine_mode,  # type: ignore[arg-type]
                zones=risks,
                sources=[
                    s.health()
                    for s in (self.weather, self.discharge, self.seismic, self.eonet, self.gdacs)
                ],
                national_level=national,  # type: ignore[arg-type]
                population_at_risk=at_risk,
                blindspot_zones=[r.zone_id for r in risks if r.blindspot],
                seismic_events=seismic[:25],
                global_events=[GlobalEvent(**ev) for ev in self.global_events],
                hazard_counts=hazard_counts,
                forecast_alarm_zones=[r.zone_id for r in risks if r.forecast_alarm],
                hf={
                    **self.hf.status(),
                    "narrative": self.narrative,
                    "replay_step": self.cursor.step,
                    "replay_total": self.cursor.total_steps(),
                    "replay_playing": self.cursor.playing,
                    "language": self.language,
                    "alarm_probability": settings.alarm_probability,
                    "forecast_horizon_h": settings.forecast_horizon_h,
                },
            )
            self.state = state
            await self._broadcast({"type": "state", "payload": state.model_dump(mode="json")})
            return state

    def _forecast_alarm_due(self, risk: ZoneRisk) -> bool:
        """Rate-limit forecast alarms per zone, so a sustained high-probability
        outlook does not re-alarm on every tick."""
        last = self._forecast_alarms.get(risk.zone_id, 0.0)
        now = time.time()
        if now - last < settings.alert_cooldown_s:
            return False
        self._forecast_alarms[risk.zone_id] = now
        return True

    # --- alerting ---------------------------------------------------------
    async def _raise_alert(
        self, risk: ZoneRisk, simulated: bool, trigger: str = "conditions"
    ) -> AlertRecord:
        top = risk.forecasts[0] if risk.forecasts else None
        if trigger == "forecast" and top is not None:
            headline = (
                f"FORECAST ALARM: {top.percent}% probability of {top.hazard} at "
                f"{risk.name} within {top.horizon_hours:.0f}h"
            )
            spoken = build_spoken(risk)
            body = (
                f"{top.percent}% probability of {top.hazard} within "
                f"{top.horizon_hours:.0f} hours. {top.basis} Method: {top.method}. "
                f"Alarm threshold is {settings.alarm_probability:.0%}."
            )
        else:
            headline = build_headline(risk)
            spoken = build_spoken(risk)
            body = risk.explanation or build_explanation(risk)

        record = AlertRecord(
            zone_id=risk.zone_id, zone_name=risk.name, level=risk.level,
            previous_level=self.machine.state(risk.zone_id).level,
            score=risk.score,
            channel="GEO" if risk.geo.score > risk.hydro.score else "HYDRO",
            headline=headline,
            body=body,
            spoken=spoken,
            cascade_eta_s=risk.cascade.eta_seconds if risk.cascade else None,
            trigger=trigger,  # type: ignore[arg-type]
            probability=top.probability if (trigger == "forecast" and top) else None,
            language=self.language,
            translations=self._translate_alert(risk, trigger, top),
            created_at=datetime.now(timezone.utc).isoformat(),
            simulated=simulated,
        )
        if self._client:
            record.dispatched = await dispatch_all(self._client, record)
        else:
            record.dispatched = ["browser-siren", "speech-synthesis", "alert-log"]

        store.record_alert(record, self.cursor.scenario_id)
        await self._broadcast({"type": "alert", "payload": record.model_dump(mode="json")})
        return record

    def _translate_alert(self, risk: ZoneRisk, trigger: str, top) -> dict[str, str]:
        """Render the spoken alert into every supported language.

        Done server-side and sent with the alert so the browser can switch
        language instantly, and so a downstream PA or SMS integration gets the
        translations without another round trip.
        """
        name = risk.name.split(" (")[0]
        out: dict[str, str] = {}
        for code in i18n.languages():
            if trigger == "forecast" and top is not None:
                key = {
                    "flood": "forecast_alarm", "landslide": "landslide_alarm",
                    "earthquake": "earthquake_alarm", "heatwave": "heat_alarm",
                }.get(top.hazard, "forecast_alarm")
                out[code] = i18n.render(
                    code, key, zone=name, percent=top.percent,
                    hours=round(top.horizon_hours),
                )
            elif risk.cascade and risk.cascade.transferred_score > risk.geo.score:
                mins = risk.cascade.eta_seconds / 60.0
                eta = f"{mins:.0f} minutes" if mins < 90 else f"{mins / 60:.1f} hours"
                out[code] = i18n.render(
                    code, "cascade_emergency", zone=name,
                    source=risk.cascade.source_zone_name.split(" (")[0], eta=eta,
                )
            elif LEVEL_RANK[risk.level] >= LEVEL_RANK["WARNING"]:
                out[code] = i18n.render(
                    code, "flood_warning", zone=name, score=round(risk.score)
                )
            else:
                out[code] = i18n.render(code, "flood_watch", zone=name)
        return out

    async def set_language(self, code: str) -> bool:
        if code not in i18n.languages():
            return False
        self.language = code
        return True

    async def simulate(self, zone_id: str, level: str = "EMERGENCY") -> AlertRecord | None:
        """Operator-triggered drill. Fires the full pipeline on demand.

        Exists because you cannot wait for real rain to cross a threshold in
        front of a panel - and because a real operations room needs to be able
        to test its own siren without a disaster.
        """
        if self.state is None:
            await self.tick(advance=False)
        assert self.state is not None
        risk = next((z for z in self.state.zones if z.zone_id == zone_id), None)
        if risk is None:
            return None
        drill = risk.model_copy(deep=True)
        drill.level = level  # type: ignore[assignment]
        drill.score = max(drill.score, settings.band_emergency)
        drill.explanation = "[DRILL] " + build_explanation(drill)
        return await self._raise_alert(drill, simulated=True, trigger="drill")

    # --- websocket fan-out ------------------------------------------------
    async def _broadcast(self, message: dict[str, Any]) -> None:
        dead = []
        for q in list(self.subscribers):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.subscribers.discard(q)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    # --- control ----------------------------------------------------------
    async def set_scenario(self, scenario_id: str) -> bool:
        self._fell_back = False
        ok = self.cursor.select(scenario_id)
        if ok:
            self.machine.reset()
            store.clear_history()
            await self.tick(advance=False)
        return ok

    async def set_engine_mode(self, mode: str) -> bool:
        if mode not in {"dual", "legacy"}:
            return False
        self.engine_mode = mode
        self.machine.reset()
        await self.tick(advance=False)
        return True


orchestrator = Orchestrator()


async def poll_forever() -> None:
    """Background loop. Replay advances at the scenario's own pace; live mode
    respects the configured poll interval."""
    while True:
        try:
            sc = orchestrator.cursor.scenario()
            interval = (
                float(sc.get("step_seconds", 2.5))
                if sc and orchestrator.cursor.playing
                else settings.poll_interval_s
            )
            await orchestrator.tick(advance=True)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must never die
            await asyncio.sleep(3.0)
