"""Runtime configuration for Prahari.

Everything is environment-driven with safe defaults, so the system boots with
zero configuration and degrades cleanly when a network or a token is missing.
That is deliberate: a demo that dies on venue wifi is a demo that scores zero.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FRONTEND_DIR = ROOT / "frontend"


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


class Settings:
    """Single source of truth for tunables. Read once at import."""

    # --- server -----------------------------------------------------------
    host: str = os.getenv("PRAHARI_HOST", "0.0.0.0")
    port: int = _env_int("PRAHARI_PORT", 8000)

    # --- data sources -----------------------------------------------------
    # LIVE calls the public APIs. REPLAY serves the bundled snapshot corpus.
    # AUTO tries live once at boot and falls back to replay if unreachable.
    source_mode: str = os.getenv("PRAHARI_SOURCE_MODE", "auto").lower()

    openmeteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    openmeteo_flood_url: str = "https://flood-api.open-meteo.com/v1/flood"
    usgs_feed_url: str = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
    )
    usgs_query_url: str = "https://earthquake.usgs.gov/fdsnws/event/1/query"

    http_timeout_s: float = _env_float("PRAHARI_HTTP_TIMEOUT", 12.0)
    # Circuit breaker: after N consecutive failures a source is parked for
    # `breaker_cooldown_s` and serves cached/replay data instead of hanging.
    breaker_threshold: int = _env_int("PRAHARI_BREAKER_THRESHOLD", 3)
    breaker_cooldown_s: float = _env_float("PRAHARI_BREAKER_COOLDOWN", 120.0)

    # --- polling ----------------------------------------------------------
    poll_interval_s: float = _env_float("PRAHARI_POLL_INTERVAL", 20.0)
    weather_refresh_s: float = _env_float("PRAHARI_WEATHER_REFRESH", 300.0)
    seismic_refresh_s: float = _env_float("PRAHARI_SEISMIC_REFRESH", 60.0)

    # --- risk engine ------------------------------------------------------
    # Band edges on the 0-100 fused score.
    band_advisory: float = _env_float("PRAHARI_BAND_ADVISORY", 40.0)
    band_watch: float = _env_float("PRAHARI_BAND_WATCH", 55.0)
    band_warning: float = _env_float("PRAHARI_BAND_WARNING", 70.0)
    band_emergency: float = _env_float("PRAHARI_BAND_EMERGENCY", 85.0)

    # Hysteresis: a zone must fall this far below a band edge to de-escalate,
    # and must hold a level this long before it is allowed to drop. Prevents
    # the siren flapping on and off around a threshold.
    hysteresis_drop: float = _env_float("PRAHARI_HYSTERESIS_DROP", 8.0)
    min_dwell_s: float = _env_float("PRAHARI_MIN_DWELL", 90.0)
    # Re-notify suppression for an unchanged level.
    alert_cooldown_s: float = _env_float("PRAHARI_ALERT_COOLDOWN", 300.0)

    # Cross-channel amplification coefficient (see engine/fusion.py).
    fusion_kappa: float = _env_float("PRAHARI_FUSION_KAPPA", 0.35)
    # Fraction of an upstream mass-movement score propagated downstream.
    cascade_transfer: float = _env_float("PRAHARI_CASCADE_TRANSFER", 0.85)
    # Seismic search radius around a geo-watch zone, kilometres.
    geo_radius_km: float = _env_float("PRAHARI_GEO_RADIUS_KM", 120.0)

    # --- Hugging Face -----------------------------------------------------
    hf_token: str | None = os.getenv("HF_TOKEN") or os.getenv(
        "HUGGINGFACEHUB_API_TOKEN"
    )
    hf_dataset_repo: str = os.getenv("PRAHARI_HF_DATASET", "prahari/geohazard-incidents")
    hf_inference_base: str = os.getenv(
        "PRAHARI_HF_INFERENCE_BASE", "https://router.huggingface.co/v1"
    )
    hf_briefing_model: str = os.getenv(
        "PRAHARI_HF_BRIEFING_MODEL", "meta-llama/Llama-3.1-8B-Instruct"
    )
    hf_embedding_model: str = os.getenv(
        "PRAHARI_HF_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )
    hf_enabled: bool = _env_bool("PRAHARI_HF_ENABLED", True)

    # --- alert fan-out ----------------------------------------------------
    webhook_url: str | None = os.getenv("PRAHARI_WEBHOOK_URL")
    twilio_sid: str | None = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_token: str | None = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_from: str = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    twilio_to: str | None = os.getenv("TWILIO_WHATSAPP_TO")

    # --- storage ----------------------------------------------------------
    db_path: Path = Path(os.getenv("PRAHARI_DB", str(ROOT / "prahari.db")))

    @property
    def twilio_enabled(self) -> bool:
        return bool(self.twilio_sid and self.twilio_token and self.twilio_to)

    def band_for(self, score: float) -> str:
        if score >= self.band_emergency:
            return "EMERGENCY"
        if score >= self.band_warning:
            return "WARNING"
        if score >= self.band_watch:
            return "WATCH"
        if score >= self.band_advisory:
            return "ADVISORY"
        return "NORMAL"


settings = Settings()

LEVEL_ORDER = ["NORMAL", "ADVISORY", "WATCH", "WARNING", "EMERGENCY"]
LEVEL_RANK = {name: i for i, name in enumerate(LEVEL_ORDER)}
