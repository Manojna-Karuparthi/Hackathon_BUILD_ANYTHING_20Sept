"""Translation integrity.

A life-safety template that silently drops a placeholder produces a
grammatical sentence missing the only number that matters. That failure is
invisible to anyone who does not read the language, so it is tested.
"""
import re

import pytest

from backend import i18n

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def test_all_languages_load():
    langs = i18n.languages()
    assert len(langs) >= 10
    assert "en" in langs and "ne" in langs and "as" in langs


def test_dialects_are_declared_with_a_voice_fallback():
    dialects = [l for l in i18n.languages().values() if l.dialect_of]
    assert dialects, "the whole point was dialect coverage"
    for d in dialects:
        assert d.dialect_of in i18n.languages()
        assert d.speech, f"{d.code} must declare a fallback voice"


def test_every_language_preserves_every_placeholder():
    english = i18n.languages()["en"].phrases
    for code, lang in i18n.languages().items():
        for key, source in english.items():
            want = set(PLACEHOLDER.findall(source))
            got = set(PLACEHOLDER.findall(lang.phrases[key]))
            assert want == got, f"{code}.{key}: expected {want}, got {got}"


def test_every_language_has_every_level_name():
    for code, lang in i18n.languages().items():
        for level in ("NORMAL", "ADVISORY", "WATCH", "WARNING", "EMERGENCY"):
            assert lang.levels.get(level), f"{code} missing level {level}"


def test_render_fills_placeholders_in_every_language():
    for code in i18n.languages():
        out = i18n.render(code, "cascade_emergency", zone="Rasuwa", source="Langtang", eta="26 minutes")
        assert "{" not in out, f"{code} left an unfilled placeholder"
        assert "Rasuwa" in out and "26 minutes" in out


def test_unknown_language_falls_back_to_english():
    assert i18n.get("xx-YY").code == "en"
    assert "Rasuwa" in i18n.render("xx", "flood_watch", zone="Rasuwa")


def test_review_status_is_declared_honestly():
    """The translations are machine-assisted and unreviewed. The system must
    say so rather than implying they are production-ready."""
    r = i18n.review_status()
    assert r["status"] == "UNREVIEWED_MACHINE_ASSISTED"
    assert "native" in r["note"].lower()
