"""Hugging Face integration.

Three distinct uses, in descending order of how much the demo depends on them:

1. DATASET (always on, no token). The historical incident corpus in
   data/hf_dataset is authored in HF dataset format with a dataset card, read
   through `datasets.load_dataset` when the library is present, and publishable
   to the Hub with scripts/push_to_hf.py. This is what the analogue engine
   retrieves over.

2. INFERENCE - alert briefings (optional, needs HF_TOKEN). Turns the engine's
   structured contributions into a short plain-language brief through a chat
   model on the HF router. Strictly a presentation layer: the model is handed
   the numbers the rules engine already computed and is forbidden from
   inventing new ones. If it is unavailable, the deterministic template in
   engine/explain.py produces the same information, just less fluently. The
   risk score itself is NEVER model-generated.

3. INFERENCE - embeddings (optional, needs HF_TOKEN). Adds a text-similarity
   view alongside the numeric analogue match, for narrative rather than
   feature-space resemblance.

The token is read from the environment and never logged or returned to the
browser; /api/health reports only whether it is present.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from .base import Source

BRIEFING_SYSTEM = (
    "You are the duty officer's assistant in a flood and geohazard operations "
    "room in South Asia. You will be given a JSON risk assessment that has "
    "ALREADY been computed by a deterministic rules engine.\n\n"
    "Write 2-3 short sentences for a district emergency coordinator.\n"
    "Hard rules:\n"
    "- Use ONLY numbers present in the JSON. Never invent, round up or estimate.\n"
    "- Never predict what will happen. Describe what is being measured and what "
    "action the level implies.\n"
    "- Lead with the single dominant driver, then the action.\n"
    "- Plain language. No jargon, no markdown, no preamble."
)


class HuggingFaceSource(Source):
    def __init__(self) -> None:
        super().__init__(name="huggingface/inference", ttl_s=45.0)

    @property
    def available(self) -> bool:
        return bool(settings.hf_enabled and settings.hf_token)

    async def briefing(
        self, client: httpx.AsyncClient, payload: dict[str, Any]
    ) -> str | None:
        """Generate a plain-language brief. Returns None on any failure."""
        if not self.available or self.breaker_open:
            return None

        import json

        body = {
            "model": settings.hf_briefing_model,
            "messages": [
                {"role": "system", "content": BRIEFING_SYSTEM},
                {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
            ],
            "max_tokens": 160,
            "temperature": 0.2,
        }
        self._calls += 1
        import time

        started = time.perf_counter()
        try:
            resp = await client.post(
                f"{settings.hf_inference_base}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {settings.hf_token}"},
                timeout=settings.http_timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
            text = (data["choices"][0]["message"]["content"] or "").strip()
            self._record_success((time.perf_counter() - started) * 1000.0)
            return text or None
        except Exception as exc:  # noqa: BLE001
            self._record_failure(f"{type(exc).__name__}: {exc}"[:200])
            return None

    async def embed(
        self, client: httpx.AsyncClient, texts: list[str]
    ) -> list[list[float]] | None:
        if not self.available or self.breaker_open:
            return None
        try:
            resp = await client.post(
                f"https://router.huggingface.co/hf-inference/models/"
                f"{settings.hf_embedding_model}/pipeline/feature-extraction",
                json={"inputs": texts},
                headers={"Authorization": f"Bearer {settings.hf_token}"},
                timeout=settings.http_timeout_s,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            self._record_failure(f"{type(exc).__name__}: {exc}"[:200])
            return None

    def status(self) -> dict[str, Any]:
        return {
            "token_present": bool(settings.hf_token),
            "enabled": settings.hf_enabled,
            "dataset_repo": settings.hf_dataset_repo,
            "briefing_model": settings.hf_briefing_model,
            "embedding_model": settings.hf_embedding_model,
            "briefing_calls": self._calls,
            "last_error": self._last_error,
        }
