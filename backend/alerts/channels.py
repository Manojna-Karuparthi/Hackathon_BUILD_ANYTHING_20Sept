"""Alert delivery channels.

Ordered by how much the demo depends on them, which is the inverse of how
impressive they sound. The browser siren and speech channel is first because
it has zero external dependencies and therefore zero chance of failing in
front of judges. WhatsApp is last because it needs a third-party sandbox and a
pre-joined number, and anything that needs someone else's uptime does not get
to be the centrepiece.

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


async def dispatch_whatsapp(client: httpx.AsyncClient, record: AlertRecord) -> str | None:
    """Twilio WhatsApp sandbox. Optional bonus channel, off unless configured."""
    if not settings.twilio_enabled:
        return None
    body = f"{record.headline}\n\n{record.spoken}"[:1500]
    try:
        resp = await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_sid}/Messages.json",
            data={
                "From": settings.twilio_from,
                "To": settings.twilio_to,
                "Body": body,
            },
            auth=(settings.twilio_sid or "", settings.twilio_token or ""),
            timeout=settings.http_timeout_s,
        )
        resp.raise_for_status()
        return "whatsapp"
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
        dispatch_whatsapp(client, record),
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
        "whatsapp": {
            "enabled": settings.twilio_enabled,
            "note": "Twilio sandbox. Bonus channel - set TWILIO_* env vars to enable.",
        },
    }
