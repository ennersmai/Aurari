"""P2-02: no code outside config.py reads a stack 0 model field directly.

``settings.l1_model`` .. ``settings.l5_model`` are the stack 0 fields. Reading
them ignores the active stack (LEAN / CORE / TITAN), so callers must use
``settings.active_lX_model`` or ``settings.model_for("lX")``.

Every ``src/aura/**/*.py`` file except ``config.py`` is tokenized (so comments
and strings, including docstrings, are ignored) and the test fails on the token
sequence ``settings . lN_model`` or ``settings . lN_model_fallback`` (use
``settings.fallback_for("lN")``, P2-02b).

The rule is deliberately limited to the name ``settings``. A rule on any
``.lN_model`` attribute would also flag ``llm_layers.l3_model`` in school.py,
the goal and learning engines and the agent loop; that is the ``LLMLayers``
property, which now returns the active stack's model, so those reads are fine.
The test below checks that property follows a stack switch.
"""

import io
import re
import sys
import tokenize
from pathlib import Path

import pytest

from aura.config import settings

SRC = Path(__file__).resolve().parents[2] / "src" / "aura"
NL = chr(10)
STACK0 = re.compile(r"l[1-5]_model(_fallback)?")


def _offences(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    toks = [
        t for t in tokenize.generate_tokens(io.StringIO(source).readline)
        if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT)
    ]
    found = []
    for a, b, c in zip(toks, toks[1:], toks[2:]):
        if (
            a.type == tokenize.NAME and a.string == "settings"
            and b.type == tokenize.OP and b.string == "."
            and c.type == tokenize.NAME and STACK0.fullmatch(c.string)
        ):
            found.append(f"{path.relative_to(SRC)}:{c.start[0]} settings.{c.string}")
    return found


def test_no_direct_stack0_model_reads():
    offences = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "config.py" and path.parent == SRC:
            continue
        offences += _offences(path)
    assert not offences, "use settings.active_lX_model or model_for():\n" + "\n".join(offences)


def test_llmlayers_models_follow_the_active_stack(monkeypatch):
    from aura.llm.layers import LLMLayers
    from aura.llm.provider import OpenRouterClient

    for stack, suffix in ((0, ""), (1, "1"), (2, "2")):
        for n in range(1, 6):
            monkeypatch.setattr(settings, f"l{n}_model{suffix}", f"x/s{stack}-l{n}")
    monkeypatch.setattr(settings, "model_stack_index", 0)
    layers = LLMLayers(client=OpenRouterClient(api_key="k"))
    for stack in (0, 1, 2):
        monkeypatch.setattr(settings, "model_stack_index", stack)
        for n in range(1, 6):
            assert getattr(layers, f"l{n}_model") == f"x/s{stack}-l{n}"


def test_model_for_rejects_unknown_layer():
    with pytest.raises(ValueError):
        settings.model_for("l6")
    with pytest.raises(ValueError):
        settings.model_for("embeddings")


@pytest.mark.parametrize("attr", ["l3_model", "l3_model_fallback"])
def test_grep_rule_catches_planted_reads(tmp_path, monkeypatch, attr):
    monkeypatch.setattr(sys.modules[__name__], "SRC", tmp_path)
    planted = tmp_path / "planted.py"
    planted.write_text("x = settings." + attr + NL, encoding="utf-8")
    assert _offences(planted)
    planted.write_text("x = settings.l3_model_fallback1  # not a stack 0 field" + NL, encoding="utf-8")
    assert not _offences(planted)
