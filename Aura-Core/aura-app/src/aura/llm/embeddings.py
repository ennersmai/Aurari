"""Local embeddings generation via nomic-embed-text-v1.5 (768 dims).

Replaces the previous OpenAI/OpenRouter cloud embedding client.
The SentenceTransformer model is loaded once at first use and reused for the
lifetime of the process.  All public methods remain async so callers need no
changes.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Optional

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Embedding dimensionality produced by nomic-embed-text-v1.5
EMBEDDING_DIMENSION = 768
_MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    """Load (and cache) the SentenceTransformer model.

    Called lazily on first embed request so the import-time cost is zero.
    ``trust_remote_code=True`` is required by the nomic model.
    """
    logger.info("Loading local embedding model '%s' …", _MODEL_NAME)
    model = SentenceTransformer(_MODEL_NAME, trust_remote_code=True)
    logger.info(
        "Embedding model loaded — dimension: %d", EMBEDDING_DIMENSION
    )
    return model


class EmbeddingsClient:
    """Async wrapper around the local SentenceTransformer model.

    The heavy ``encode`` call is dispatched to a thread-pool executor so the
    FastAPI event loop is never blocked.
    """

    def __init__(self) -> None:
        self.dimension = EMBEDDING_DIMENSION

    # ------------------------------------------------------------------
    # Public async API (drop-in replacement for the old OpenAI client)
    # ------------------------------------------------------------------

    async def embed(self, text: str) -> Optional[list[float]]:
        """Generate a 768-dimensional embedding for *text*.

        Returns ``None`` on empty / whitespace-only input.
        """
        if not text or not text.strip():
            logger.warning("embed() called with empty text — skipping")
            return None

        try:
            loop = asyncio.get_running_loop()
            embedding: list[float] = await loop.run_in_executor(
                None, self._encode_sync, text
            )
            return embedding
        except Exception as exc:
            logger.error("Local embedding failed: %s", exc)
            return None

    async def embed_batch(
        self, texts: list[str]
    ) -> list[Optional[list[float]]]:
        """Generate embeddings for a list of texts.

        Texts that are empty or whitespace produce ``None`` in the output list.
        Non-empty texts are encoded in a single batched call for efficiency.
        """
        if not texts:
            return []

        # Separate valid from invalid indices
        valid_indices: list[int] = []
        valid_texts: list[str] = []
        for i, t in enumerate(texts):
            if t and t.strip():
                valid_indices.append(i)
                valid_texts.append(t)

        results: list[Optional[list[float]]] = [None] * len(texts)

        if valid_texts:
            try:
                loop = asyncio.get_running_loop()
                vectors: list[list[float]] = await loop.run_in_executor(
                    None, self._encode_batch_sync, valid_texts
                )
                for idx, vec in zip(valid_indices, vectors):
                    results[idx] = vec
            except Exception as exc:
                logger.error("Local batch embedding failed: %s", exc)

        return results

    async def close(self) -> None:
        """No-op: local model holds no network connections."""

    # ------------------------------------------------------------------
    # Sync helpers (run inside executor)
    # ------------------------------------------------------------------

    def _encode_sync(self, text: str) -> list[float]:
        model = _load_model()
        vector = model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def _encode_batch_sync(self, texts: list[str]) -> list[list[float]]:
        model = _load_model()
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=32)
        return [v.tolist() for v in vectors]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_embeddings_client: Optional[EmbeddingsClient] = None


def get_embeddings_client() -> EmbeddingsClient:
    """Return the process-wide :class:`EmbeddingsClient` singleton."""
    global _embeddings_client
    if _embeddings_client is None:
        _embeddings_client = EmbeddingsClient()
    return _embeddings_client
