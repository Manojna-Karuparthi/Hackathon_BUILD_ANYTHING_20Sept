"""The tick loop: pull inputs, score every zone, decide alerts, fan out.

One pass through here produces one complete SystemState, which is what both
the REST snapshot and the WebSocket push serve. Keeping a single code path for
live and replay means the thing demonstrated on stage is the thing that runs.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from .alerts.channels import dispatch_all
from .config import LEVEL_RANK, settings
from .engine.analogue import find_analogues
from .engine.explain import build_explanation, build_headline, build_spoken
from .engine.fusion import build_zone_risk, compute_cascades
from .engine.geo import score_geo
from .engine.hydro import score_hydro
from .engine.state import AlertStateMachine
from .models import AlertRecord, SystemState, ZoneRisk
from .sources.huggingface import HuggingFaceSource
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
        self.hf = HuggingFaceSource()
        self.cursor = ReplayCursor()
        self.machine = AlertStateMachine()

        self.engine_mode: str = "dual"          # "dual" | "legacy"
        self.state: SystemState | None = None
        self.narrative: str = ""
        self.subscribers: set[asyncio.Queue] = set()
        self.pending_alerts: list[AlertRecord] = []
        self._client: httpx.AsyncClient | None = None
        self._live_ok: bool | None = None
        self._fell_back: bool = False
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
                    await self._raise_alert(risk, simulated=not self.cursor.is_live)

            national = max(
                (r.level for r in risks), key=lambda lv: LEVEL_RANK[lv], default="NORMAL"
            )
            at_risk = sum(
                r.population for r in risks if LEVEL_RANK[r.level] >= LEVEL_RANK["WATCH"]
            )

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
                sources=[s.health() for s in (self.weather, self.discharge, self.seismic)],
                national_level=national,  # type: ignore[arg-type]
                population_at_risk=at_risk,
                blindspot_zones=[r.zone_id for r in risks if r.blindspot],
                seismic_events=seismic[:25],
                hf={
                    **self.hf.status(),
                    "narrative": self.narrative,
                    "replay_step": self.cursor.step,
                    "replay_total": self.cursor.total_steps(),
                    "replay_playing": self.cursor.playing,
                },
            )
            self.state = state
            await self._broadcast({"type": "state", "payload": state.model_dump(mode="json")})
            return state

    # --- alerting ---------------------------------------------------------
    async def _raise_alert(self, risk: ZoneRisk, simulated: bool) -> AlertRecord:
        record = AlertRecord(
            zone_id=risk.zone_id, zone_name=risk.name, level=risk.level,
            previous_level=self.machine.state(risk.zone_id).level,
            score=risk.score,
            channel="GEO" if risk.geo.score > risk.hydro.score else "HYDRO",
            headline=build_headline(risk),
            body=risk.explanation or build_explanation(risk),
            spoken=build_spoken(risk),
            cascade_eta_s=risk.cascade.eta_seconds if risk.cascade else None,
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
        return await self._raise_alert(drill, simulated=True)

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
