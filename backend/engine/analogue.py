"""Historical analogue retrieval - the ML-shaped part, done honestly.

This does NOT predict anything. It takes the nine normalised features the risk
engine has already computed for a zone right now, and finds the documented
historical events whose signature is closest in that same feature space by
cosine similarity.

That distinction matters and is worth saying out loud in a demo: we cannot
validate a trained flood-prediction model in a day, and anyone claiming to
have done so is overselling. Retrieval over a curated corpus is defensible,
inspectable, and answers the question an operator actually asks at 3am -
"have we seen this before, and what happened?"

The corpus ships as a Hugging Face dataset (data/hf_dataset). It loads through
`datasets` when installed, and falls back to a plain JSONL read otherwise, so
the analogue panel never goes blank.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import numpy as np

from ..config import DATA_DIR, settings
from ..models import Analogue, ChannelScore
from ..zones import Zone

FEATURE_ORDER = [
    "rain_24h",
    "rain_intensity",
    "discharge_anomaly",
    "seismic_energy",
    "shallowness",
    "mass_movement_signature",
    "clustering",
    "cryosphere",
    "onset_speed",
]

# Mechanism discrimination lives mostly in the seismic/mass-movement block, so
# those dimensions are weighted up. Without this, every monsoon event looks
# alike and drowns out the rarer, deadlier signatures.
FEATURE_WEIGHTS = np.array([1.0, 0.9, 1.0, 1.25, 1.25, 1.6, 1.0, 1.1, 1.2])


@lru_cache(maxsize=1)
def load_corpus() -> tuple[list[dict[str, Any]], str]:
    """Return (incidents, provenance). Tries HF `datasets`, falls back to JSONL."""
    path = DATA_DIR / "hf_dataset" / "incidents.jsonl"
    try:
        from datasets import load_dataset  # type: ignore

        ds = load_dataset("json", data_files=str(path), split="train")
        return [dict(r) for r in ds], f"huggingface-datasets:{settings.hf_dataset_repo}"
    except Exception:  # noqa: BLE001 - `datasets` is optional by design
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        return rows, "local-jsonl"


@lru_cache(maxsize=1)
def _matrix() -> tuple[np.ndarray, list[dict[str, Any]]]:
    rows, _ = load_corpus()
    mat = np.array(
        [[float(r["features"].get(k, 0.0)) for k in FEATURE_ORDER] for r in rows],
        dtype=float,
    )
    return mat * FEATURE_WEIGHTS, rows


def _norm(values: list[Any], key: str) -> float:
    for c in values:
        if c.key == key:
            return float(c.normalised)
    return 0.0


def live_vector(zone: Zone, hydro: ChannelScore, geo: ChannelScore) -> np.ndarray:
    """Project the current state into the corpus feature space."""
    h, g = hydro.contributions, geo.contributions

    rain_24h = _norm(h, "rain_24h")
    rain_intensity = _norm(h, "rain_1h")
    discharge = _norm(h, "discharge")
    energy = _norm(g, "energy")
    shallow = _norm(g, "shallow")
    signature = _norm(g, "signature")
    cluster = _norm(g, "cluster")
    cryo = 1.0 if zone.cryosphere.get("glacier_area_km2") else 0.0

    # Onset speed: seismic-led events are effectively instantaneous; rainfall
    # events are paced by how fast accumulation is intensifying.
    trend = _norm(h, "trend")
    onset = max(signature * 0.95, min(trend * 0.8, 0.8))

    vec = np.array(
        [rain_24h, rain_intensity, discharge, energy, shallow, signature, cluster, cryo, onset],
        dtype=float,
    )
    return vec * FEATURE_WEIGHTS


def find_analogues(
    zone: Zone, hydro: ChannelScore, geo: ChannelScore, top_k: int = 3, floor: float = 0.55
) -> list[Analogue]:
    vec = live_vector(zone, hydro, geo)
    if float(np.linalg.norm(vec)) < 0.15:
        return []  # Nothing is happening; an analogue would be noise.

    mat, rows = _matrix()
    denom = np.linalg.norm(mat, axis=1) * np.linalg.norm(vec)
    denom[denom == 0] = 1e-9
    sims = (mat @ vec) / denom

    order = np.argsort(-sims)[:top_k]
    out: list[Analogue] = []
    for idx in order:
        sim = float(sims[idx])
        if sim < floor:
            continue
        row = rows[idx]
        out.append(
            Analogue(
                incident_id=row["incident_id"],
                title=row["title"],
                date=row["date"],
                similarity=round(sim, 3),
                mechanism=row["mechanism"].replace("_", " "),
                outcome=row["outcome"],
                lesson=row["lesson"],
            )
        )
    return out
