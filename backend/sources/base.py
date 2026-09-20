"""Source adapter base: shared HTTP client, caching and a circuit breaker.

Every external feed goes through this. The contract is that `fetch()` never
raises and never blocks the poll loop for longer than the timeout: on failure
it returns the last good payload (marked stale) or hands control to the replay
corpus. An early-warning system that goes silent when a feed flaps is worse
than useless, so degradation is always explicit and visible in /api/health.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import settings
from ..models import SourceHealth


@dataclass
class CacheEntry:
    payload: Any
    fetched_at: float


@dataclass
class Source:
    name: str
    ttl_s: float = 300.0

    _cache: dict[str, CacheEntry] = field(default_factory=dict, init=False)
    _failures: int = field(default=0, init=False)
    _opened_at: float = field(default=0.0, init=False)
    _last_success: float | None = field(default=None, init=False)
    _last_error: str | None = field(default=None, init=False)
    _latency_ms: float | None = field(default=None, init=False)
    _calls: int = field(default=0, init=False)
    _mode: str = field(default="live", init=False)

    # --- circuit breaker --------------------------------------------------
    @property
    def breaker_open(self) -> bool:
        if self._failures < settings.breaker_threshold:
            return False
        if time.time() - self._opened_at > settings.breaker_cooldown_s:
            # Half-open: allow one probe through.
            self._failures = settings.breaker_threshold - 1
            return False
        return True

    def _record_success(self, latency_ms: float) -> None:
        self._failures = 0
        self._last_success = time.time()
        self._last_error = None
        self._latency_ms = latency_ms
        self._mode = "live"

    def _record_failure(self, err: str) -> None:
        self._failures += 1
        self._last_error = err
        if self._failures >= settings.breaker_threshold:
            self._opened_at = time.time()
        self._mode = "cache" if self._cache else "down"

    # --- cache ------------------------------------------------------------
    def cached(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        return entry.payload

    def fresh(self, key: str) -> bool:
        entry = self._cache.get(key)
        return entry is not None and (time.time() - entry.fetched_at) < self.ttl_s

    def store(self, key: str, payload: Any) -> None:
        self._cache[key] = CacheEntry(payload, time.time())

    # --- http -------------------------------------------------------------
    async def get_json(
        self, client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None
    ) -> Any | None:
        if self.breaker_open:
            return None
        self._calls += 1
        started = time.perf_counter()
        try:
            resp = await client.get(url, params=params, timeout=settings.http_timeout_s)
            resp.raise_for_status()
            data = resp.json()
            self._record_success((time.perf_counter() - started) * 1000.0)
            return data
        except Exception as exc:  # noqa: BLE001 - any failure degrades identically
            self._record_failure(f"{type(exc).__name__}: {exc}"[:200])
            return None

    def mark_replay(self) -> None:
        self._mode = "replay"

    def health(self) -> SourceHealth:
        from datetime import datetime, timezone

        def iso(ts: float | None) -> str | None:
            if ts is None:
                return None
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        mode = self._mode
        if mode not in {"live", "replay", "cache", "down"}:
            mode = "down"
        return SourceHealth(
            name=self.name,
            mode=mode,  # type: ignore[arg-type]
            last_success=iso(self._last_success),
            last_error=self._last_error,
            latency_ms=round(self._latency_ms, 1) if self._latency_ms else None,
            consecutive_failures=self._failures,
            calls=self._calls,
        )
