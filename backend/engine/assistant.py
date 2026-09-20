"""The situation assistant.

Answers "what is happening and what do I do" in any supported language.

Two tiers, deliberately in this order:

1. INTENT MATCHING over the live system state, answering from the SAME
   translated safety templates the sirens use. Works offline, in every
   language, with no token and no model. The safety-critical answers live
   here, because a person asking "should I leave" must not depend on an API
   being up.

2. HUGGING FACE INFERENCE for anything free-form, grounded in a JSON snapshot
   of the current state and explicitly forbidden from inventing numbers.
   Optional. Absent a token, tier 1 answers and says what it could not cover.

The assistant never invents a risk number and never overrides the engine. It
reads state out loud; it does not decide.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .. import i18n
from ..config import LEVEL_RANK, settings

# Intent keywords across the supported languages, plus romanised forms, since
# people type Devanagari-language queries in Latin script constantly.
INTENTS: dict[str, list[str]] = {
    "status": [
        "what is happening", "what's happening", "status", "situation", "now",
        "kya ho raha", "क्या हो रहा", "के भइरहेको", "स्थिति", "परिस्थिति",
        "ki hocche", "কি হচ্ছে", "ఏమి జరుగుతోంది", "என்ன நடக்கிறது", "کیا ہو رہا",
    ],
    "safety": [
        "am i safe", "safe", "danger", "should i leave", "evacuate", "risk to me",
        "surakshit", "सुरक्षित", "खतरा", "ख़तरा", "নিরাপদ", "సురక్షితం", "பாதுகாப்பு",
        "محفوظ",
    ],
    "action": [
        "what should i do", "what do i do", "action", "instructions", "help",
        "kya karu", "क्या करूँ", "के गर्ने", "কি করব", "ఏమి చేయాలి", "என்ன செய்வது",
        "کیا کروں",
    ],
    "eta": [
        "when", "how long", "arrive", "time", "kab", "कब", "कहिले", "কখন",
        "ఎప్పుడు", "எப்போது", "کب",
    ],
    "why": ["why", "reason", "because", "kyun", "क्यों", "किन", "কেন", "ఎందుకు", "ஏன்", "کیوں"],
    "forecast": [
        "forecast", "predict", "prediction", "will", "chance", "probability", "next",
        "bhavishya", "भविष्य", "पूर्वानुमान", "पूर्वानुमान", "সম্ভাবনা", "అంచనా",
        "முன்னறிவிப்பு", "پیش گوئی",
    ],
    "hazards": [
        "hazard", "disaster", "world", "global", "earthquake", "fire", "cyclone",
        "volcano", "map", "आपदा", "भूकंप", "विपद्", "দুর্যোগ", "విపత్తు", "பேரிடர்",
        "آفت",
    ],
}


@dataclass
class Answer:
    text: str
    speak: str
    language: str
    intent: str
    source: str                 # "rules" | "hf-inference"
    zone_id: str | None = None
    suggestions: list[str] | None = None


def detect_intent(question: str) -> str:
    q = question.lower().strip()
    best, score = "status", 0
    for intent, keys in INTENTS.items():
        for k in keys:
            if k.lower() in q:
                # Prefer the longest match: "what should i do" must beat "do".
                if len(k) > score:
                    best, score = intent, len(k)
    return best if score else "status"


def _fmt_eta(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds <= 0:
        return "now"
    m = seconds / 60.0
    if m < 90:
        return f"{m:.0f} minutes"
    return f"{m / 60.0:.1f} hours"


def _pick_zone(state: dict[str, Any], question: str, zone_id: str | None) -> dict[str, Any] | None:
    zones = state.get("zones") or []
    if not zones:
        return None
    if zone_id:
        found = next((z for z in zones if z["zone_id"] == zone_id), None)
        if found:
            return found
    # Name mentioned in the question wins over the default.
    q = question.lower()
    for z in zones:
        if z["name"].split(" (")[0].lower() in q:
            return z
    # Otherwise the most dangerous zone - which is what someone asking a bare
    # "what's happening" almost always means.
    return max(zones, key=lambda z: LEVEL_RANK.get(z["level"], 0) * 1000 + z["score"])


def answer(
    state: dict[str, Any],
    question: str,
    lang_code: str = "en",
    zone_id: str | None = None,
) -> Answer:
    intent = detect_intent(question)
    zone = _pick_zone(state, question, zone_id)
    lang = i18n.get(lang_code)

    if zone is None:
        txt = "No zone data is available yet."
        return Answer(txt, txt, lang.code, intent, "rules")

    name = zone["name"].split(" (")[0]
    level = zone["level"]
    level_local = i18n.level_name(lang.code, level)
    score = round(zone["score"])
    cascade = zone.get("cascade")
    forecasts = zone.get("forecasts") or []

    # --- safety-critical intents answer from the siren templates ----------
    if intent in {"safety", "action", "status"} and LEVEL_RANK.get(level, 0) >= LEVEL_RANK["WATCH"]:
        if cascade and cascade.get("transferred_score", 0) > zone["geo"]["score"]:
            speak = i18n.render(
                lang.code, "cascade_emergency", zone=name,
                source=cascade["source_zone_name"].split(" (")[0],
                eta=_fmt_eta(cascade.get("eta_seconds")),
            )
        elif LEVEL_RANK.get(level, 0) >= LEVEL_RANK["WARNING"]:
            speak = i18n.render(lang.code, "flood_warning", zone=name, score=score)
        else:
            speak = i18n.render(lang.code, "flood_watch", zone=name)
        text = f"{name}: {level_local} ({score}/100). {speak}"
        return Answer(text, speak, lang.code, intent, "rules", zone["zone_id"])

    if intent == "eta":
        if cascade:
            speak = i18n.render(
                lang.code, "cascade_emergency", zone=name,
                source=cascade["source_zone_name"].split(" (")[0],
                eta=_fmt_eta(cascade.get("eta_seconds")),
            )
            text = (
                f"{speak} [{_fmt_eta(cascade.get('eta_seconds'))} from "
                f"{cascade['source_zone_name']}, {cascade['distance_km']:.0f} km upstream]"
            )
        else:
            text = f"{name} has no inbound surge with an arrival estimate right now."
            speak = text
        return Answer(text, speak, lang.code, intent, "rules", zone["zone_id"])

    if intent == "forecast":
        if not forecasts:
            text = f"No forecast is available for {name} right now."
            return Answer(text, text, lang.code, intent, "rules", zone["zone_id"])
        top = forecasts[0]
        pct = round(top["probability"] * 100)
        key = {
            "flood": "forecast_alarm", "landslide": "landslide_alarm",
            "earthquake": "earthquake_alarm", "heatwave": "heat_alarm",
        }.get(top["hazard"], "forecast_alarm")
        speak = i18n.render(
            lang.code, key, zone=name, percent=pct, hours=round(top["horizon_hours"])
        )
        # Lead with the translated sentence so what is shown matches what is
        # spoken. The method line stays in English on purpose: it is a
        # citation, and mistranslating a method name would make it
        # unverifiable.
        text = (
            f"{speak} [{pct}% · {top['band']} · {round(top['horizon_hours'])}h] "
            f"Method: {top['method']}."
        )
        return Answer(text, speak, lang.code, intent, "rules", zone["zone_id"])

    if intent == "why":
        # The explanation is generated from the engine's own contribution
        # detail strings, which are English technical text. It is shown as-is
        # rather than machine-translated, because a mistranslated threshold
        # citation is worse than an untranslated one.
        text = zone.get("explanation") or f"{name} is at {level_local}."
        return Answer(text, text, lang.code, intent, "rules", zone["zone_id"])

    if intent == "hazards":
        events = state.get("global_events") or []
        by_kind: dict[str, int] = {}
        for ev in events:
            by_kind[ev["hazard"]] = by_kind.get(ev["hazard"], 0) + 1
        if not by_kind:
            text = "No global hazard events are currently loaded."
        else:
            parts = ", ".join(
                f"{n} {k}" for k, n in sorted(by_kind.items(), key=lambda kv: -kv[1])
            )
            text = f"{len(events)} active hazard events worldwide: {parts}."
        return Answer(text, text, lang.code, intent, "rules")

    # --- calm state -------------------------------------------------------
    speak = i18n.render(lang.code, "all_clear", zone=name) if level == "NORMAL" else (
        f"{name}: {level_local}, {score}/100."
    )
    text = f"{name} is at {level_local} ({score}/100). {zone.get('explanation','')}".strip()
    return Answer(text, speak, lang.code, intent, "rules", zone["zone_id"])


# ------------------------------------------------------------ HF tier ------
SYSTEM = (
    "You are the assistant in a disaster operations room. You are given a JSON "
    "snapshot of a risk assessment produced by a deterministic rules engine, and a "
    "question from a member of the public or a district officer.\n\n"
    "Rules you must not break:\n"
    "- Use ONLY numbers that appear in the JSON. Never invent, estimate or round up.\n"
    "- Never predict anything the JSON does not already carry a probability for.\n"
    "- If the JSON does not answer the question, say so plainly.\n"
    "- Answer in the language named in 'reply_language'. If unsure, use English.\n"
    "- Two or three short sentences. Action first. No markdown, no preamble.\n"
    "- If a level is WARNING or EMERGENCY, the first sentence must be the action."
)


def hf_payload(
    state: dict[str, Any], question: str, lang_code: str, zone: dict[str, Any] | None
) -> dict[str, Any]:
    """Compact grounding payload - small enough to be cheap, complete enough
    that the model never needs to guess."""
    lang = i18n.get(lang_code)
    out: dict[str, Any] = {
        "reply_language": f"{lang.name} ({lang.native})",
        "question": question[:500],
        "national_level": state.get("national_level"),
        "population_at_risk": state.get("population_at_risk"),
        "alarm_probability_threshold": settings.alarm_probability,
    }
    if zone:
        out["zone"] = {
            "name": zone["name"], "level": zone["level"], "score": round(zone["score"]),
            "legacy_score": round(zone.get("legacy_score", 0)),
            "explanation": zone.get("explanation"),
            "cascade_eta_seconds": (zone.get("cascade") or {}).get("eta_seconds"),
            "forecasts": [
                {
                    "hazard": f["hazard"], "probability": f["probability"],
                    "horizon_hours": f["horizon_hours"], "band": f["band"],
                }
                for f in (zone.get("forecasts") or [])[:3]
            ],
        }
    return out


def starter_questions(lang_code: str = "en") -> list[str]:
    """Shown as tappable chips. English prompts are matched by the intent
    keywords in every language, so these stay useful even untranslated."""
    return [
        "What is happening right now?",
        "Am I safe?",
        "What should I do?",
        "When will the water arrive?",
        "What is the forecast?",
        "Show global hazards",
    ]
