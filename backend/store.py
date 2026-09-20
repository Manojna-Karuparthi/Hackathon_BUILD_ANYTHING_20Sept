"""SQLite persistence for the alert log and score history.

Deliberately stdlib-only: no database to install, no service to start, and the
file is a single artefact a judge can inspect. The alert log is the
accountability record - who was told what, when, and on which evidence.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .models import AlertRecord

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id TEXT NOT NULL,
    zone_name TEXT NOT NULL,
    level TEXT NOT NULL,
    previous_level TEXT NOT NULL,
    score REAL NOT NULL,
    channel TEXT NOT NULL,
    headline TEXT NOT NULL,
    body TEXT NOT NULL,
    spoken TEXT NOT NULL,
    cascade_eta_s REAL,
    dispatched TEXT NOT NULL DEFAULT '[]',
    simulated INTEGER NOT NULL DEFAULT 0,
    scenario TEXT NOT NULL DEFAULT 'live',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_zone ON alerts(zone_id);

CREATE TABLE IF NOT EXISTS score_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id TEXT NOT NULL,
    score REAL NOT NULL,
    legacy_score REAL NOT NULL,
    hydro REAL NOT NULL,
    geo REAL NOT NULL,
    level TEXT NOT NULL,
    scenario TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hist_zone ON score_history(zone_id, id DESC);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.executescript(SCHEMA)


def record_alert(
    record: AlertRecord, scenario: str = "live"
) -> AlertRecord:
    with _lock, _connect() as conn:
        cur = conn.execute(
            """INSERT INTO alerts (zone_id, zone_name, level, previous_level, score,
                    channel, headline, body, spoken, cascade_eta_s, dispatched,
                    simulated, scenario, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record.zone_id, record.zone_name, record.level, record.previous_level,
                record.score, record.channel, record.headline, record.body, record.spoken,
                record.cascade_eta_s, json.dumps(record.dispatched),
                int(record.simulated), scenario, record.created_at,
            ),
        )
        record.id = cur.lastrowid
    return record


def recent_alerts(limit: int = 50) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["dispatched"] = json.loads(d.get("dispatched") or "[]")
        d["simulated"] = bool(d["simulated"])
        out.append(d)
    return out


def record_scores(rows: list[tuple[str, float, float, float, float, str]], scenario: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        conn.executemany(
            """INSERT INTO score_history
               (zone_id, score, legacy_score, hydro, geo, level, scenario, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            [(z, s, ls, h, g, lvl, scenario, now) for z, s, ls, h, g, lvl in rows],
        )


def zone_history(zone_id: str, limit: int = 60) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            """SELECT score, legacy_score, hydro, geo, level, created_at
               FROM score_history WHERE zone_id = ? ORDER BY id DESC LIMIT ?""",
            (zone_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def clear_history() -> None:
    """Reset between scenario runs so the demo chart starts clean."""
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM score_history")


def stats() -> dict[str, Any]:
    with _lock, _connect() as conn:
        alerts = conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"]
        hist = conn.execute("SELECT COUNT(*) c FROM score_history").fetchone()["c"]
    return {"alerts": alerts, "score_samples": hist, "db_path": str(settings.db_path)}
