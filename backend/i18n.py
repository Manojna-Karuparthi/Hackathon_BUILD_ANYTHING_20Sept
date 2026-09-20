"""Multilingual alert rendering.

Life-safety messages are template-based, not free-form translation. The
templates live in data/i18n/languages.json with their placeholders declared,
and every language is validated at load to carry exactly the same placeholder
set as English. A translation that silently drops {eta} would produce a
grammatical sentence that omits the only number that matters, and that failure
would be invisible - so it is checked rather than trusted.

Dialects (Bhojpuri, Maithili) carry their own text but fall back to a related
speech voice, because no TTS engine ships a voice for them. That fallback is
declared in the data and surfaced in the API rather than hidden.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .config import DATA_DIR

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    native: str
    speech: tuple[str, ...]
    rtl: bool
    dialect_of: str | None
    levels: dict[str, str]
    phrases: dict[str, str]

    @property
    def speech_primary(self) -> str:
        return self.speech[0] if self.speech else "en-IN"


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    with open(DATA_DIR / "i18n" / "languages.json", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def languages() -> dict[str, Language]:
    data = _raw()
    out: dict[str, Language] = {}
    english: dict[str, str] | None = None

    for entry in data["languages"]:
        lang = Language(
            code=entry["code"], name=entry["name"], native=entry["native"],
            speech=tuple(entry.get("speech", [])), rtl=bool(entry.get("rtl")),
            dialect_of=entry.get("dialect_of"),
            levels=dict(entry["levels"]), phrases=dict(entry["phrases"]),
        )
        if english is None:
            english = lang.phrases
        else:
            _validate(lang, english)
        out[lang.code] = lang
    return out


def _validate(lang: Language, english: dict[str, str]) -> None:
    for key, source in english.items():
        if key not in lang.phrases:
            raise ValueError(f"{lang.code}: missing phrase '{key}'")
        want = set(_PLACEHOLDER.findall(source))
        got = set(_PLACEHOLDER.findall(lang.phrases[key]))
        if want != got:
            raise ValueError(
                f"{lang.code}.{key}: placeholder mismatch, expected {sorted(want)} "
                f"got {sorted(got)}"
            )


def get(code: str) -> Language:
    langs = languages()
    if code in langs:
        return langs[code]
    # Fall back to the parent variety, then to English.
    base = code.split("-")[0]
    return langs.get(base, langs["en"])


def render(code: str, key: str, **values: Any) -> str:
    """Fill a translated template. Missing keys degrade to English."""
    lang = get(code)
    template = lang.phrases.get(key) or languages()["en"].phrases.get(key, "")
    try:
        return template.format(**values)
    except KeyError:
        # A placeholder we were not given: fall back rather than raise, because
        # an alert that renders imperfectly still beats an alert that throws.
        safe = {p: values.get(p, "") for p in _PLACEHOLDER.findall(template)}
        return template.format(**safe)


def level_name(code: str, level: str) -> str:
    return get(code).levels.get(level, level)


def catalogue() -> list[dict[str, Any]]:
    data = _raw()
    return [
        {
            "code": l.code, "name": l.name, "native": l.native,
            "speech": list(l.speech), "speech_primary": l.speech_primary,
            "rtl": l.rtl, "dialect_of": l.dialect_of,
            "voice_fallback": bool(l.dialect_of),
        }
        for l in languages().values()
    ]


def review_status() -> dict[str, Any]:
    data = _raw()
    return {
        "status": data.get("review_status"),
        "note": data.get("review_note"),
        "languages": len(languages()),
        "dialects": sum(1 for l in languages().values() if l.dialect_of),
    }
