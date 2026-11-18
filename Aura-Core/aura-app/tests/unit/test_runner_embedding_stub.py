"""W2-27: deterministic embedding stub in the scenario runner.

The scenario runner (W2-01) ships a ``HashedBagOfWordsEmbeddings`` stub
in ``tests/scenarios/runner.py`` so scenarios can run offline without
the real embedding model.  W2-12 found a latent bug in the stub: the
hash slice ``int.from_bytes(h[:4,], "little")`` used a *tuple* subscript
(``[:4,]``) instead of a slice (``[:4]``), which raised ``TypeError`` for
any non-empty text.  W2-12's embedded test worked around the bug by
storing empty content (which short-circuits the stub before the broken
line); W2-27 fixes the slice so real text embeds again.

These tests pin the stub's contract: a non-empty sentence returns a
vector of the schema's expected length (768), with at least one non-zero
entry, and the same sentence produces the same vector twice (the stub
is deterministic — BLAKE2b over lowercased whitespace tokens, L2
normalised).  They do not change the vector length or the normalisation
(the card's "Do not").
"""

import pytest

from tests.scenarios.runner import HashedBagOfWordsEmbeddings, _EMBED_DIM


@pytest.mark.asyncio
async def test_stub_returns_vector_of_expected_length():
    """A non-empty sentence embeds to a 768-dim vector (the schema's
    ``embedding`` field length, which the stub must match exactly)."""
    emb = HashedBagOfWordsEmbeddings()
    vec = await emb.embed("I like hiking in the mountains")
    assert vec is not None
    assert len(vec) == _EMBED_DIM


@pytest.mark.asyncio
async def test_stub_vector_has_at_least_one_nonzero_entry():
    """A non-empty sentence produces a vector that is not all zeros — at
    least one hashed token bucket is populated, so the L2-normalised
    vector has at least one non-zero entry."""
    emb = HashedBagOfWordsEmbeddings()
    vec = await emb.embed("I like hiking in the mountains")
    assert vec is not None
    assert any(v != 0.0 for v in vec)


@pytest.mark.asyncio
async def test_stub_is_deterministic_same_sentence_same_vector():
    """The stub is deterministic: embedding the same sentence twice
    returns byte-identical vectors.  This is what makes the scenario
    runner reproducible offline."""
    emb = HashedBagOfWordsEmbeddings()
    first = await emb.embed("I like hiking in the mountains")
    second = await emb.embed("I like hiking in the mountains")
    assert first is not None
    assert second is not None
    assert first == second
