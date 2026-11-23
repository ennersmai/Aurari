"""Tests for the emotion translator lexicon and sentence templates (FX-01 v2)."""

import random

import pytest

from aura.engines.emotion.translator import LEXICON, EmotionTranslator
from aura.models.emotion import EmotionVector

DASH = "—"
FIELDS = list(EmotionVector.model_fields)
LEVELS = ("low", "medium", "high")
VALUE_FOR = {"low": 0.2, "medium": 0.5, "high": 0.9}


def _first_up(text):
    return text[:1].upper() + text[1:]


def _vec(**kw):
    return EmotionVector(**kw)


def test_field_count():
    assert len(FIELDS) == 27
    assert set(LEXICON) == set(FIELDS)


@pytest.mark.parametrize("name", FIELDS)
def test_lexicon_covers_every_field(name):
    assert name in LEXICON
    for kind in ("noun", "verb", "adj"):
        for lvl in LEVELS:
            assert LEXICON[name][kind][lvl].strip()


def test_nouns_have_no_leading_article():
    for name, entry in LEXICON.items():
        for lvl in LEVELS:
            noun = entry["noun"][lvl].lower()
            assert not noun.startswith(("a ", "an ", "the ")), (name, lvl, noun)


@pytest.mark.parametrize("name", FIELDS)
@pytest.mark.parametrize("lvl", LEVELS)
def test_single_emotion_exact(name, lvl):
    out = EmotionTranslator().translate(_vec(**{name: VALUE_FOR[lvl]}))
    expected = f"{_first_up(LEXICON[name]['noun'][lvl])} {LEXICON[name]['verb'][lvl]}."
    assert out == expected
    for level in LEVELS:
        assert f"{level} {name}" not in out


def test_single_example_from_lexicon():
    assert EmotionTranslator().translate(_vec(curiosity=0.5)) == (
        "Bright curiosity pulls at your attention."
    )


def test_blend_connector_follows_secondary_intensity():
    tr = EmotionTranslator()
    assert tr.translate(_vec(curiosity=0.5, joy=0.25)) == (
        "Bright curiosity pulls at your attention, with a trace of quiet gladness."
    )
    assert tr.translate(_vec(curiosity=0.5, joy=0.4)) == (
        "Bright curiosity pulls at your attention, threaded with bright joy."
    )
    assert tr.translate(_vec(curiosity=0.8, joy=0.7)) == (
        "Electric curiosity makes you want to know everything, alongside radiant delight."
    )


def test_tertiary_clause_uses_its_own_intensity():
    tr = EmotionTranslator()
    assert tr.translate(_vec(curiosity=0.5, joy=0.4, doubt=0.3)) == (
        "Bright curiosity pulls at your attention, threaded with bright joy, "
        "and underneath it, faint doubt."
    )
    assert tr.translate(_vec(curiosity=0.9, joy=0.7, doubt=0.5)) == (
        "Electric curiosity makes you want to know everything, alongside radiant delight, "
        "and underneath it, nagging doubt."
    )
    # Below 0.3 the tertiary is left out.
    assert "underneath" not in tr.translate(_vec(curiosity=0.5, joy=0.4, doubt=0.25))


def test_neutral_line():
    assert EmotionTranslator().translate(_vec()) == (
        "A calm, neutral state: emotions at rest, waiting for what comes next."
    )


def test_mastery_lines():
    tr = EmotionTranslator()
    base = tr.translate(_vec(joy=0.5))
    high = tr.translate(_vec(joy=0.5), {"confidence_level": 0.9, "mastery_level": 0.9})
    mid = tr.translate(_vec(joy=0.5), {"confidence_level": 0.9, "mastery_level": 0.7})
    low = tr.translate(_vec(joy=0.5), {"confidence_level": 0.9, "mastery_level": 0.3})
    assert high == base + " You feel confident here; these patterns are familiar."
    assert mid == base + " You recognize these patterns from experience."
    assert low == base


def test_random_vectors_render_cleanly():
    rng = random.Random(1234)
    tr = EmotionTranslator()
    for _ in range(50):
        vec = _vec(**{n: round(rng.random(), 3) for n in FIELDS})
        out = tr.translate(vec)
        assert DASH not in out
        assert "  " not in out
        assert ",." not in out
        assert out.endswith(".") and not out.endswith("..")
        assert out[0].isupper()
        for name in FIELDS:
            for lvl in LEVELS:
                assert f"{lvl} {name}" not in out


@pytest.mark.parametrize(
    "kw, expected",
    [
        (dict(curiosity=0.55, joy=0.40),
         "Bright curiosity pulls at your attention, threaded with bright joy."),
        (dict(curiosity=0.55, joy=0.25),
         "Bright curiosity pulls at your attention, with a trace of quiet gladness."),
        (dict(curiosity=0.55, joy=0.40, doubt=0.31),
         "Bright curiosity pulls at your attention, threaded with bright joy, "
         "and underneath it, faint doubt."),
        (dict(anger=0.70, doubt=0.50),
         "Hot anger burns close to the surface, threaded with nagging doubt."),
    ],
)
def test_fx02_plan_examples(kw, expected):
    zero = {f: 0.0 for f in FIELDS}
    zero.update(kw)
    assert EmotionTranslator().translate(EmotionVector(**zero)) == expected
