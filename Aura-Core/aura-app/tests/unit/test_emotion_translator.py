"""Tests for the emotion translator lexicon and em dash polish (FX-01)."""

import itertools

import pytest

from aura.engines.emotion.translator import LEXICON, EmotionTranslator
from aura.models.emotion import EmotionVector

DASH = "—"
FIELDS = list(EmotionVector.model_fields)
LEVELS = ("low", "medium", "high")


def _fallback_phrases(name):
    return [f"{lvl} {name}" for lvl in LEVELS]


@pytest.mark.parametrize("name", FIELDS)
def test_lexicon_covers_every_field(name):
    assert name in LEXICON
    for kind in ("noun", "verb", "adj"):
        for lvl in LEVELS:
            assert LEXICON[name][kind][lvl]


@pytest.mark.parametrize("name", FIELDS)
@pytest.mark.parametrize("value", [0.2, 0.5, 0.9])
def test_single_emotion_clean(name, value):
    out = EmotionTranslator().translate(EmotionVector(**{name: value}))
    assert DASH not in out
    for phrase in _fallback_phrases(name):
        assert phrase not in out


def test_combined_states_clean():
    pairs = [
        ("beauty", "disgust", "envy"),
        ("disgust", "envy", "beauty"),
        ("envy", "beauty", "disgust"),
        ("beauty", "joy", "envy"),
        ("disgust", "fear", "beauty"),
        ("envy", "sadness", "disgust"),
        ("joy", "beauty", "love"),
        ("anger", "disgust", "envy"),
        ("awe", "beauty", "serenity"),
        ("pride", "envy", "shame"),
    ]
    tr = EmotionTranslator()
    outs = []
    for a, b, c in pairs:
        for vals in ((0.9, 0.5, 0.35), (0.5, 0.4, 0.3)):
            vec = EmotionVector(**{a: vals[0], b: vals[1], c: vals[2]})
            outs.append(tr.translate(vec))
    assert len(outs) == 20
    for out in outs:
        assert DASH not in out
        for name in ("beauty", "disgust", "envy"):
            for phrase in _fallback_phrases(name):
                assert phrase not in out


def test_neutral_and_mastery_lines_clean():
    tr = EmotionTranslator()
    assert DASH not in tr.translate(EmotionVector())
    for mastery in (0.9, 0.7):
        out = tr.translate(
            EmotionVector(joy=0.5),
            learning_context={"confidence_level": 0.9, "mastery_level": mastery},
        )
        assert DASH not in out
        assert "You feel confident here;" in out or "You recognize these patterns," in out
