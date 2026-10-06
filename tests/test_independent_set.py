"""Schema and coverage checks for eval/independent_blind.jsonl.

These tests deliberately do NOT score the router on the set; the set is scored
once by scripts/score_independent.py and the number is frozen in
eval/INDEPENDENT_RESULTS.md. Here we only guard the file's shape so it cannot
silently drift.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SET = ROOT / "eval" / "independent_blind.jsonl"

INTENTS = {"habit", "rule", "court", "report", "source", "gate", "checklist", "help"}
LANGS = {"en", "zh"}
FIELDS = {"text", "intent", "lang", "needs_context", "previous_intent", "note"}


def _rows() -> list[dict]:
    with open(SET, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_file_exists_and_has_200_rows():
    assert SET.exists()
    assert len(_rows()) == 200


def test_every_row_matches_schema():
    for i, r in enumerate(_rows()):
        assert set(r) == FIELDS, f"line {i + 1}: fields {sorted(r)}"
        assert isinstance(r["text"], str) and r["text"].strip(), f"line {i + 1}: empty text"
        assert r["intent"] in INTENTS, f"line {i + 1}: intent {r['intent']!r}"
        assert r["lang"] in LANGS, f"line {i + 1}: lang {r['lang']!r}"
        assert isinstance(r["needs_context"], bool), f"line {i + 1}: needs_context not bool"
        assert r["previous_intent"] is None or r["previous_intent"] in INTENTS, f"line {i + 1}"
        assert isinstance(r["note"], str), f"line {i + 1}: note not str"


def test_needs_context_rows_carry_previous_intent():
    for i, r in enumerate(_rows()):
        if r["needs_context"]:
            assert r["previous_intent"] is not None, f"line {i + 1}: needs_context without previous_intent"


def test_no_duplicate_texts():
    texts = [r["text"] for r in _rows()]
    dupes = [t for t, c in Counter(texts).items() if c > 1]
    assert not dupes, dupes


def test_language_split():
    langs = Counter(r["lang"] for r in _rows())
    assert langs["en"] == 110
    assert langs["zh"] == 90


def test_every_intent_covered_in_both_languages():
    seen = Counter((r["lang"], r["intent"]) for r in _rows())
    for lang in LANGS:
        for intent in INTENTS:
            assert seen[(lang, intent)] >= 8, f"{lang}/{intent} has only {seen[(lang, intent)]} rows"


def test_intent_balance():
    by_intent = Counter(r["intent"] for r in _rows())
    assert set(by_intent) == INTENTS
    # help is the catch-all and is allowed to be about a quarter of the set
    assert 40 <= by_intent["help"] <= 60
    for intent in INTENTS - {"help"}:
        assert 15 <= by_intent[intent] <= 30, f"{intent}: {by_intent[intent]}"


def test_minimum_slice_sizes():
    rows = _rows()
    assert sum(r["needs_context"] for r in rows) >= 20
    assert sum("adversarial" in r["note"] and r["intent"] == "help" for r in rows) >= 25
    assert sum("ambiguous" in r["note"] for r in rows) >= 15
