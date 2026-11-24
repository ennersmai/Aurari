"""Taught and imported skills (G6-02). No model call anywhere in this module.

A teaching turn that describes a procedure becomes a skill draft built from the
owner's own words. Owner-taught skills are trusted (PRD); a guest's teaching and
every import is an unapproved candidate with an owner decision (``propose_skill``).
"""

import re
from typing import Any

from aura.config import settings

_LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+\S", re.MULTILINE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_IMPERATIVES = frozenset(
    "open run use check click select add remove create make send copy paste write read "
    "install start stop save download upload set go ask tell find search "
    "log login enter type press push pull commit deploy build test restart delete "
    "update edit fill submit navigate visit call connect configure ensure verify "
    "wait choose pick put move rename review list show take".split()
)
# Lead-in words skipped before looking for the verb ("First, open ...").
_LEAD_WORDS = frozenset("first then next finally after also now and please".split())
_NAME_MAX = 48


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s and s.strip()]


def _first_word(sentence: str) -> str:
    words = re.findall(r"[A-Za-z']+", sentence)
    while len(words) > 1 and words[0].lower() in _LEAD_WORDS:
        words.pop(0)
    return words[0].lower() if words else ""


def describes_procedure(text: str) -> bool:
    """True for a numbered or bulleted list (two or more items), or at least two
    sentences that start with an imperative verb. A plain preference is False."""
    if not text or not text.strip():
        return False
    if len(_LIST_ITEM.findall(text)) >= 2:
        return True
    imperative = [s for s in _sentences(text) if _first_word(s) in _IMPERATIVES]
    return len(imperative) >= 2


def _clean_first_line(text: str) -> str:
    for sentence in _sentences(text):
        line = re.sub(r"^\s*(?:\d+[.)]|[-*•#])\s*", "", sentence).strip()
        if line:
            return line
    return ""


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:_NAME_MAX].strip("-")


def build_taught_draft(text: str) -> dict[str, Any] | None:
    """Draft from the owner's words: body is the text, first sentence is
    ``when_to_use``. None when empty or over ``skill_body_max_chars``."""
    body = (text or "").strip()
    if not body or len(body) > settings.skill_body_max_chars:
        return None
    when = _clean_first_line(body)
    name = slugify(when)
    if not when or not name:
        return None
    return {"name": name, "when_to_use": when, "tags": ["taught"], "body": body}


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Split a minimal ``---`` / ``key: value`` / ``---`` header from the body.

    Raises ValueError for a header that never closes or has a line that is not
    ``key: value``. Tags may be ``[a, b]`` or ``a, b``. Without a header the whole
    text is the body.
    """
    stripped = text.lstrip("﻿")
    lines = stripped.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, stripped.strip()
    meta: dict[str, Any] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return meta, "\n".join(lines[i + 1:]).strip()
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        key = key.strip().lower()
        if not sep or not re.fullmatch(r"[a-z_]+", key):
            raise ValueError(f"malformed front matter line: {line[:60]!r}")
        value = value.strip().strip("'\"")
        if key == "tags":
            value = value.strip("[]")
            meta["tags"] = [t.strip().strip("'\"") for t in value.split(",") if t.strip()]
        else:
            meta[key] = value
    raise ValueError("front matter is not closed with ---")


def parse_import(name: str | None, text: Any) -> dict[str, Any]:
    """Parse an imported skill file into a draft. Raises ValueError when refused."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("skill text is empty")
    if len(text) > settings.skill_body_max_chars:
        raise ValueError(f"skill text is over {settings.skill_body_max_chars} characters")
    meta, body = parse_front_matter(text)
    if not body:
        raise ValueError("skill has no body")
    when = (meta.get("when_to_use") or "").strip() or _clean_first_line(body)
    skill_name = slugify(name or meta.get("name") or when)
    if not when or not skill_name:
        raise ValueError("skill needs a name or a when_to_use")
    return {"name": skill_name, "when_to_use": when, "tags": meta.get("tags") or [], "body": body}


async def propose_taught(
    store: Any, embeddings: Any, text: str, speaker: str, decisions: Any = None
) -> bool:
    """Teach a skill from ``text``. Owner: trusted and live. Anyone else: an inert
    candidate with a decision. Returns True when a proposal was made."""
    from aura.engines.learning.skill_proposals import propose_skill

    if not (settings.skills_v2_enabled and settings.skill_taught_enabled):
        return False
    if not describes_procedure(text):
        return False
    draft = build_taught_draft(text)
    if draft is None:
        return False
    owner = speaker == "owner"
    await propose_skill(
        store, embeddings, draft, source="taught",
        origin_speaker="owner" if owner else "guest",
        decisions=decisions, pre_approved=owner,
    )
    return True
