"""Prahari API.

REST for snapshots and control, WebSocket for push. The dashboard opens one
socket and is driven entirely by `state` and `alert` frames; the REST routes
exist so the system is inspectable with curl, which matters when a judge asks
"is that real or is it hardcoded".
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import i18n, store
from .alerts.channels import channel_status
from .config import FRONTEND_DIR, settings
from .engine.analogue import load_corpus
from .engine.assistant import answer as assistant_answer
from .engine.assistant import hf_payload, starter_questions
from .hazards import catalogue as hazard_catalogue
from .engine.hydro import WEIGHTS as HYDRO_WEIGHTS
from .engine.geo import WEIGHTS as GEO_WEIGHTS
from .orchestrator import orchestrator, poll_forever
from .sources.replay import list_scenarios
from .zones import basins, zones

_task: asyncio.Task | None = None


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global _task
    await orchestrator.start()
    await orchestrator.tick(advance=False)
    _task = asyncio.create_task(poll_forever())
    try:
        yield
    finally:
        if _task:
            _task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await _task
        await orchestrator.stop()


app = FastAPI(
    title="Prahari",
    description="Dual-channel geohazard early warning: rainfall AND ground motion.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# --------------------------------------------------------------------- state
@app.get("/api/state")
async def get_state() -> Any:
    if orchestrator.state is None:
        await orchestrator.tick(advance=False)
    assert orchestrator.state is not None
    return orchestrator.state.model_dump(mode="json")


@app.get("/api/zones")
async def get_zones() -> Any:
    return {
        "zones": [
            {
                "id": z.id, "name": z.name, "admin": z.admin, "country": z.country,
                "lat": z.lat, "lon": z.lon, "population": z.population,
                "basin": z.basin, "river": z.river, "terrain": z.terrain,
                "terrain_factor": z.terrain_factor, "vulnerability": z.vulnerability,
                "geo_watch": z.geo_watch, "wards": list(z.wards), "notes": z.notes,
                "cryosphere": z.cryosphere,
                "rain_24h_threshold_mm": round(z.rain_24h_threshold, 1),
                "rain_1h_threshold_mm": round(z.rain_1h_threshold, 1),
            }
            for z in zones()
        ],
        "basins": [
            {
                "id": b.id, "name": b.name, "country": b.country, "head_zone": b.head_zone,
                "description": b.description,
                "reaches": [
                    {"from": r.src, "to": r.dst, "distance_km": r.distance_km,
                     "velocity_ms": r.velocity_ms, "gradient": r.gradient}
                    for r in b.reaches
                ],
            }
            for b in basins()
        ],
    }


@app.get("/api/zone/{zone_id}/history")
async def get_history(zone_id: str, limit: int = 80) -> Any:
    return {"zone_id": zone_id, "history": store.zone_history(zone_id, limit)}


@app.get("/api/alerts")
async def get_alerts(limit: int = 50) -> Any:
    return {"alerts": store.recent_alerts(limit)}


# ------------------------------------------------------------------- control
@app.get("/api/scenarios")
async def get_scenarios() -> Any:
    return {
        "scenarios": [s.model_dump(mode="json") for s in list_scenarios()],
        "active": orchestrator.cursor.scenario_id,
        "step": orchestrator.cursor.step,
        "playing": orchestrator.cursor.playing,
    }


@app.post("/api/scenario/{scenario_id}")
async def set_scenario(scenario_id: str) -> Any:
    if not await orchestrator.set_scenario(scenario_id):
        raise HTTPException(404, f"Unknown scenario '{scenario_id}'")
    return {"ok": True, "scenario": scenario_id}


@app.post("/api/playback/{action}")
async def playback(action: str, step: int | None = None) -> Any:
    cur = orchestrator.cursor
    if cur.is_live:
        raise HTTPException(400, "Playback control applies to scenarios, not live mode.")
    if action == "play":
        cur.playing = True
    elif action == "pause":
        cur.playing = False
    elif action == "step":
        cur.playing = False
        cur.seek(cur.step + 1)
        await orchestrator.tick(advance=False)
    elif action == "restart":
        cur.seek(0)
        orchestrator.machine.reset()
        store.clear_history()
        await orchestrator.tick(advance=False)
    elif action == "seek" and step is not None:
        cur.playing = False
        cur.seek(step)
        await orchestrator.tick(advance=False)
    else:
        raise HTTPException(400, f"Unknown playback action '{action}'")
    return {"ok": True, "step": cur.step, "playing": cur.playing}


@app.post("/api/engine/{mode}")
async def set_engine(mode: str) -> Any:
    """Switch between dual-channel and the legacy rainfall-only counterfactual."""
    if not await orchestrator.set_engine_mode(mode):
        raise HTTPException(400, "mode must be 'dual' or 'legacy'")
    return {"ok": True, "engine_mode": mode}


@app.post("/api/simulate/{zone_id}")
async def simulate(zone_id: str, level: str = "EMERGENCY") -> Any:
    """Fire the full alert pipeline on demand - the demo trigger and the
    real-world drill button."""
    record = await orchestrator.simulate(zone_id, level)
    if record is None:
        raise HTTPException(404, f"Unknown zone '{zone_id}'")
    return record.model_dump(mode="json")


# ------------------------------------------------------------- multi-hazard
@app.get("/api/hazards")
async def hazards() -> Any:
    """The hazard taxonomy the map legend and filters are built from."""
    return {"hazards": hazard_catalogue()}


@app.get("/api/global-events")
async def global_events(hazard: str | None = None, limit: int = 300) -> Any:
    """Live worldwide hazard events, normalised across NASA EONET, GDACS and USGS."""
    events = orchestrator.global_events
    if hazard:
        wanted = {h.strip() for h in hazard.split(",") if h.strip()}
        events = [e for e in events if e["hazard"] in wanted]
    return {
        "count": len(events),
        "events": events[:limit],
        "sources": [orchestrator.eonet.health().model_dump(mode="json"),
                    orchestrator.gdacs.health().model_dump(mode="json")],
    }


@app.get("/api/forecasts")
async def forecasts() -> Any:
    """Every zone forecast, strongest probability first."""
    if orchestrator.state is None:
        await orchestrator.tick(advance=False)
    assert orchestrator.state is not None
    rows = []
    for z in orchestrator.state.zones:
        for f in z.forecasts:
            rows.append({
                "zone_id": z.zone_id, "zone": z.name,
                **f.model_dump(mode="json"),
            })
    rows.sort(key=lambda r: -r["probability"])
    return {
        "alarm_threshold": settings.alarm_probability,
        "horizon_hours": settings.forecast_horizon_h,
        "forecasts": rows,
    }


# ------------------------------------------------------------------ language
@app.get("/api/languages")
async def languages() -> Any:
    return {
        "languages": i18n.catalogue(),
        "active": orchestrator.language,
        "review": i18n.review_status(),
    }


@app.post("/api/language/{code}")
async def set_language(code: str) -> Any:
    if not await orchestrator.set_language(code):
        raise HTTPException(404, f"Unsupported language '{code}'")
    return {"ok": True, "language": code}


# ----------------------------------------------------------------- assistant
@app.get("/api/assistant/starters")
async def assistant_starters(lang: str = "en") -> Any:
    return {"questions": starter_questions(lang)}


@app.post("/api/assistant")
async def assistant(
    question: str = Body(..., embed=True),
    lang: str = Body("en", embed=True),
    zone_id: str | None = Body(None, embed=True),
    allow_llm: bool = Body(True, embed=True),
) -> Any:
    """Answer a question about the current situation, in the chosen language.

    Rules tier answers first and always works offline. The LLM tier only runs
    for free-form questions, is grounded in the state snapshot, and can never
    change a risk number.
    """
    if orchestrator.state is None:
        await orchestrator.tick(advance=False)
    assert orchestrator.state is not None
    state = orchestrator.state.model_dump(mode="json")

    reply = assistant_answer(state, question, lang, zone_id)
    result = {
        "text": reply.text, "speak": reply.speak, "language": reply.language,
        "intent": reply.intent, "source": reply.source, "zone_id": reply.zone_id,
        "speech_lang": i18n.get(reply.language).speech_primary,
        "rtl": i18n.get(reply.language).rtl,
    }

    # Escalate to the model only when the rules tier had no specific intent and
    # a token is configured.
    if allow_llm and reply.intent == "status" and orchestrator.hf.available:
        zone = next(
            (z for z in state["zones"] if z["zone_id"] == reply.zone_id), None
        )
        payload = hf_payload(state, question, lang, zone)
        if orchestrator._client is not None:
            text = await orchestrator.hf.briefing(orchestrator._client, payload)
            if text:
                result["text"] = text
                result["speak"] = text
                result["source"] = "hf-inference"
    return result


# -------------------------------------------------------------------- health
@app.get("/api/health")
async def health() -> Any:
    corpus, provenance = load_corpus()
    return {
        "status": "ok",
        "source_mode": settings.source_mode,
        "active_scenario": orchestrator.cursor.scenario_id,
        "engine_mode": orchestrator.engine_mode,
        "sources": [
            s.health().model_dump(mode="json")
            for s in (
                orchestrator.weather, orchestrator.discharge, orchestrator.seismic,
                orchestrator.eonet, orchestrator.gdacs,
            )
        ],
        "languages": i18n.review_status(),
        "global_events": len(orchestrator.global_events),
        "huggingface": orchestrator.hf.status(),
        "corpus": {"incidents": len(corpus), "provenance": provenance},
        "channels": channel_status(),
        "store": store.stats(),
        "websocket_subscribers": len(orchestrator.subscribers),
    }


@app.get("/api/methodology")
async def methodology() -> Any:
    """The scoring formula, served as data. Every weight on screen is from here."""
    return {
        "hydro": {
            "weights": HYDRO_WEIGHTS,
            "anchors": {
                "rain_24h_mm": "IMD 'very heavy' 115.6 mm, scaled by zone terrain factor",
                "rain_1h_mm": "IMD cloudburst 50 mm/h, scaled by zone terrain factor",
                "discharge": "ECMWF GloFAS modelled discharge vs seasonal mean; 2.5x anchors a major flood",
            },
            "curve": "n = 1 - exp(-1.609 * x / threshold); n = 0.80 exactly at threshold",
            "exposure": "score = hazard * (0.80 + 0.40 * vulnerability)",
        },
        "geo": {
            "weights": GEO_WEIGHTS,
            "gate": "score = sum(points) * exp(-distance_km / 45)",
            "mass_movement_window": "M1.8-4.8, depth <= 10 km, glaciated or steep catchment",
            "note": "Detection of mass movement already in progress. Not earthquake prediction.",
        },
        "fusion": {
            "formula": "R = max(A, B) + kappa * (min/100) * (max/100) * 100",
            "kappa": settings.fusion_kappa,
            "why_not_mean": "A mean lets a silent channel dilute a screaming one. That is the failure mode this project exists to fix.",
        },
        "cascade": {
            "trigger_score": 45.0,
            "transfer": settings.cascade_transfer,
            "decay_km": 260.0,
            "eta": "Summed per-reach: distance / debris_velocity, from data/zones.json",
        },
        "bands": {
            "ADVISORY": settings.band_advisory, "WATCH": settings.band_watch,
            "WARNING": settings.band_warning, "EMERGENCY": settings.band_emergency,
        },
        "forecast": {
            "flood": "NWP threshold-exceedance on Open-Meteo (ECMWF/GFS) forecast precipitation",
            "aftershock": "Reasenberg & Jones (1989) with Omori-Utsu decay; P(at least one) via Poisson",
            "landslide": "Caine (1980) rainfall intensity-duration threshold I = 14.82 * D^-0.39",
            "heat": "IMD heatwave temperature criteria vs forecast maximum",
            "alarm_probability": settings.alarm_probability,
            "horizon_hours": settings.forecast_horizon_h,
            "note": (
                "These forecast a hazard's likelihood, not an earthquake's occurrence. "
                "Aftershock probability is conditional on a mainshock that has already "
                "happened - a solved problem. Forecasting a first earthquake is not."
            ),
        },
        "state_machine": {
            "hysteresis_drop": settings.hysteresis_drop,
            "min_dwell_s": settings.min_dwell_s,
            "cooldown_s": settings.alert_cooldown_s,
            "rule": "Escalation is immediate and never suppressed. Only de-escalation is damped.",
        },
    }


# ----------------------------------------------------------------- websocket
@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()
    queue = orchestrator.subscribe()
    try:
        if orchestrator.state is not None:
            await socket.send_json(
                {"type": "state", "payload": orchestrator.state.model_dump(mode="json")}
            )
        while True:
            message = await queue.get()
            await socket.send_json(message)
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        pass
    finally:
        orchestrator.unsubscribe(queue)


# ------------------------------------------------------------------ frontend
@app.get("/")
async def index() -> Any:
    path = FRONTEND_DIR / "index.html"
    if not path.exists():
        return JSONResponse({"error": "frontend not built"}, status_code=404)
    return FileResponse(path)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
