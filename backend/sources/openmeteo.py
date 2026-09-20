"""Open-Meteo adapters: rainfall (Forecast API) and river discharge (GloFAS).

Both are free, key-less and documented for non-commercial use, which is why
they are the live backbone of the demo. The Flood API serves ECMWF GloFAS
river discharge - actual modelled streamflow, not a rainfall proxy - so
Channel A gets a genuine second hydrological input rather than one signal
counted twice.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from ..zones import Zone
from .base import Source


class WeatherSource(Source):
    def __init__(self) -> None:
        super().__init__(name="open-meteo/forecast", ttl_s=settings.weather_refresh_s)

    async def fetch(
        self, client: httpx.AsyncClient, zones: list[Zone]
    ) -> dict[str, dict[str, Any]]:
        """One batched call for every zone. Open-Meteo accepts comma-joined
        coordinate lists and returns a list of per-location results, so 10
        zones cost one request instead of ten."""
        key = "all"
        if self.fresh(key):
            return self.cached(key) or {}

        params = {
            "latitude": ",".join(f"{z.lat:.4f}" for z in zones),
            "longitude": ",".join(f"{z.lon:.4f}" for z in zones),
            "hourly": "precipitation,rain,soil_moisture_0_to_1cm,temperature_2m",
            "past_hours": 72,
            "forecast_hours": 48,
            "timezone": "UTC",
        }
        raw = await self.get_json(client, settings.openmeteo_forecast_url, params)
        if raw is None:
            return self.cached(key) or {}

        blocks = raw if isinstance(raw, list) else [raw]
        out: dict[str, dict[str, Any]] = {}
        for zone, block in zip(zones, blocks):
            hourly = (block or {}).get("hourly", {}) or {}
            precip = [p or 0.0 for p in hourly.get("precipitation", [])]
            soil = [s for s in hourly.get("soil_moisture_0_to_1cm", []) if s is not None]
            temp = [t for t in hourly.get("temperature_2m", []) if t is not None]
            out[zone.id] = _summarise(precip, soil, hourly.get("time", []), temp)
        self.store(key, out)
        return out


class DischargeSource(Source):
    def __init__(self) -> None:
        super().__init__(name="open-meteo/glofas-flood", ttl_s=max(settings.weather_refresh_s, 900))

    async def fetch(
        self, client: httpx.AsyncClient, zones: list[Zone]
    ) -> dict[str, dict[str, Any]]:
        key = "all"
        if self.fresh(key):
            return self.cached(key) or {}

        params = {
            "latitude": ",".join(f"{z.lat:.4f}" for z in zones),
            "longitude": ",".join(f"{z.lon:.4f}" for z in zones),
            "daily": "river_discharge,river_discharge_mean,river_discharge_max",
            "past_days": 7,
            "forecast_days": 3,
        }
        raw = await self.get_json(client, settings.openmeteo_flood_url, params)
        if raw is None:
            return self.cached(key) or {}

        blocks = raw if isinstance(raw, list) else [raw]
        out: dict[str, dict[str, Any]] = {}
        for zone, block in zip(zones, blocks):
            daily = (block or {}).get("daily", {}) or {}
            series = [v for v in daily.get("river_discharge", []) if v is not None]
            mean = [v for v in daily.get("river_discharge_mean", []) if v is not None]
            current = series[7] if len(series) > 7 else (series[-1] if series else None)
            baseline = (sum(mean) / len(mean)) if mean else (
                sum(series) / len(series) if series else None
            )
            ratio = None
            if current is not None and baseline:
                ratio = current / baseline
            out[zone.id] = {
                "discharge_m3s": current,
                "baseline_m3s": baseline,
                "anomaly_ratio": ratio,
                "series": series[-10:],
            }
        self.store(key, out)
        return out


def _summarise(
    precip: list[float],
    soil: list[float],
    times: list[str],
    temp: list[float] | None = None,
) -> dict[str, Any]:
    """Collapse an hourly series into the numbers the engine and the
    forecasters actually use. The forward window matters as much as the past
    one now: it is what the prediction layer runs on."""
    past = precip[:72] if len(precip) >= 72 else precip
    recent_1h = past[-1] if past else 0.0
    recent_3h = sum(past[-3:]) if past else 0.0
    acc_24h = sum(past[-24:]) if past else 0.0
    acc_72h = sum(past) if past else 0.0
    # Trend: last 6h rate vs the 6h before it. Positive means intensifying.
    last6 = sum(past[-6:]) if len(past) >= 6 else sum(past)
    prev6 = sum(past[-12:-6]) if len(past) >= 12 else 0.0
    trend = last6 - prev6
    forecast_6h = sum(precip[72:78]) if len(precip) > 72 else 0.0
    forecast_24h = sum(precip[72:96]) if len(precip) > 72 else 0.0
    forecast_48h = sum(precip[72:120]) if len(precip) > 72 else 0.0
    temp = temp or []
    temp_fwd = temp[72:120] if len(temp) > 72 else temp[-24:]
    return {
        "rain_1h_mm": round(recent_1h, 2),
        "rain_3h_mm": round(recent_3h, 2),
        "rain_24h_mm": round(acc_24h, 2),
        "rain_72h_mm": round(acc_72h, 2),
        "trend_6h_mm": round(trend, 2),
        "forecast_6h_mm": round(forecast_6h, 2),
        "forecast_24h_mm": round(forecast_24h, 2),
        "forecast_48h_mm": round(forecast_48h, 2),
        "forecast_series": [round(v, 2) for v in precip[72:96]],
        "temp_max_c": round(max(temp_fwd), 1) if temp_fwd else None,
        "temp_now_c": round(temp[71], 1) if len(temp) > 71 else (round(temp[-1], 1) if temp else None),
        "soil_moisture": round(soil[-1], 3) if soil else None,
        "series_24h": [round(v, 2) for v in past[-24:]],
        "last_time": times[-1] if times else None,
    }
