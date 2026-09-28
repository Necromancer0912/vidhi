"""
NyayaBot — Cross-encoder re-ranker.

Default model: BAAI/bge-reranker-v2-m3
  - Multilingual (English + Hindi queries work correctly)
  - Significantly more accurate than MiniLM on domain-specific legal text
  - ~0.6 GB VRAM on RTX 4060 Ti, runs in ~15ms for top-20 chunks
  - Uses sigmoid scores (0-1 range), higher = more relevant

Fallback model (fast, set RERANKER_MODEL env var):
  cross-encoder/ms-marco-MiniLM-L-6-v2
  - English-only, ~200 MB, ~4ms — good for low-resource dev machines
"""

from __future__ import annotations

import logging
from functools import lru_cache

from src.config import settings
from src.models import Chunk

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """
    Cross-encoder reranker. Scores (query, passage) pairs jointly — much more
    accurate than the bi-encoder retrieval stage.

    We run it only on the top-20 RRF candidates, not the full corpus.

    bge-reranker-v2-m3 specifics:
      - Automatically uses CUDA if torch.cuda.is_available()
      - Returns raw logits; we apply sigmoid to get 0–1 relevance scores
      - Accepts Hindi queries natively (multilingual training)
    """

    def __init__(self, model_name: str = None):
        self.model_name = model_name or settings.reranker_model
        self._model = None
        self._device = None
        logger.info(f"CrossEncoderReranker initialised (lazy load): {self.model_name}")

    def _load(self) -> None:
        if self._model is not None:
            return

        import torch
        from sentence_transformers import CrossEncoder

        if torch.backends.mps.is_available():
            self._device = "mps"
        elif torch.cuda.is_available():
            self._device = "cuda"
        else:
            self._device = "cpu"
            
        logger.info(f"Loading cross-encoder '{self.model_name}' on {self._device.upper()}...")

        self._model = CrossEncoder(
            self.model_name,
            max_length=512,
            device=self._device,
        )
        logger.info(f"✓ Cross-encoder ready: {self.model_name} on {self._device.upper()}")

    def rerank(self, query: str, chunks: list[Chunk], top_k: int = None) -> list[Chunk]:
        """
        Re-rank chunks for the given query using the cross-encoder.

        Args:
            query:  The user's question (English or Hindi).
            chunks: Candidate chunks from RRF (typically top-20).
            top_k:  How many to return. Defaults to settings.top_k_rerank.

        Returns:
            top_k chunks sorted by cross-encoder score, descending.
        """
        top_k = top_k or settings.top_k_rerank

        if not chunks:
            return []

        if self.model_name == "passthrough":
            logger.info("Reranker is set to 'passthrough'. Keeping original RRF ranking order.")
            return chunks[:top_k]

        self._load()
        if len(chunks) == 1:
            return chunks[:top_k]

        # Build (query, passage) pairs — truncate passages to 512 tokens worth of chars
        pairs = [(query, chunk.text[:1500]) for chunk in chunks]

        # predict() returns raw logits for bge-reranker; sigmoid → 0-1 relevance score
        raw_scores = self._model.predict(pairs, show_progress_bar=False)

        # Apply sigmoid so scores are interpretable (bge outputs logits, not probabilities)
        import math

        scores = [1.0 / (1.0 + math.exp(-float(s))) for s in raw_scores]

        # Sort by score descending and return top_k
        scored = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)

        result = []
        for chunk, score in scored[:top_k]:
            reranked = chunk.model_copy()
            reranked.score = float(score)
            result.append(reranked)

        return result


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoderReranker:
    """Singleton getter. Model is lazy-loaded on first rerank() call."""
    return CrossEncoderReranker()
