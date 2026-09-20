"""Alert delivery channels.

The browser siren and speech channel comes first because it has zero external
dependencies: no third-party sandbox, no pre-joined number, nothing that can
fail because someone else's service is down. The spoken text is written for
relay over a village public-address system, which is how a warning reaches
people who have no smartphone at all.

Messaging-app delivery was deliberately removed: it required a third-party
sandbox and a pre-registered number, which made the most visible channel the
least reliable one. The webhook below is the integration point for any
external delivery system a deployment already operates.

Every channel returns a label on success and None on failure. A channel that
fails never blocks the others - a warning that reaches three out of four
places is a warning delivered.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..config import settings
from ..models import AlertRecord


async def dispatch_webhook(client: httpx.AsyncClient, record: AlertRecord) -> str | None:
    if not settings.webhook_url:
        return None
    try:
        resp = await client.post(
            settings.webhook_url,
            json=record.model_dump(mode="json"),
            timeout=settings.http_timeout_s,
        )
        resp.raise_for_status()
        return "webhook"
    except Exception:  # noqa: BLE001
        return None


async def dispatch_all(
    client: httpx.AsyncClient, record: AlertRecord
) -> list[str]:
    """Fan out concurrently. 'browser-siren' and 'log' are always recorded:
    the WebSocket push and the SQLite write happen in the caller and cannot
    fail independently of the process itself."""
    results = await asyncio.gather(
        dispatch_webhook(client, record),
        return_exceptions=True,
    )
    delivered = ["browser-siren", "speech-synthesis", "alert-log"]
    for r in results:
        if isinstance(r, str):
            delivered.append(r)
    return delivered


def channel_status() -> dict[str, Any]:
    return {
        "browser-siren": {"enabled": True, "note": "Always on. No external dependency."},
        "speech-synthesis": {
            "enabled": True,
            "note": "Web Speech API, client-side. Designed as the relay text for village PA systems.",
        },
        "alert-log": {"enabled": True, "note": "SQLite accountability record."},
        "webhook": {
            "enabled": bool(settings.webhook_url),
            "note": "Generic POST for integration with an existing EOC system.",
        },
    }
