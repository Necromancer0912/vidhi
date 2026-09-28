"""
NyayaBot — BM25 sparse retrieval over in-memory corpus.
We maintain a BM25 index of chunk texts, updated on startup.
"""

from __future__ import annotations

import logging
import os
import pickle
from pathlib import Path
from typing import Optional

from rank_bm25 import BM25Okapi

from src.models import Chunk

logger = logging.getLogger(__name__)


class BM25Retriever:
    """
    BM25-based sparse retrieval over the chunk corpus.

    The BM25 index is built from chunks.json (produced during ingestion)
    to avoid re-embedding. For production: rebuild weekly via cron.
    """

    INDEX_PATH = Path("data/processed/bm25_index.pkl")

    def __init__(self, chunks: list[Chunk] = None):
        self.chunks: list[Chunk] = []
        self.tokenized_corpus: list[list[str]] = []
        self.bm25: Optional[BM25Okapi] = None

        if chunks:
            self.build_index(chunks)

    def build_index(self, chunks: list[Chunk]) -> None:
        """Build BM25 index from a list of chunks."""
        logger.info(f"Building BM25 index from {len(chunks)} chunks")
        self.chunks = chunks
        self.tokenized_corpus = [self._tokenize(chunk.text) for chunk in chunks]
        self.bm25 = BM25Okapi(self.tokenized_corpus)
        logger.info("BM25 index built successfully")

    def retrieve(
        self, query: str, top_k: int = 20, category_filter: Optional[str] = None
    ) -> list[Chunk]:
        """Retrieve top_k chunks by BM25 score, optionally filtered by act_category."""
        if not self.bm25:
            logger.warning("BM25 index not built — returning empty")
            return []

        tokenized_query = self._tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)

        # Get top_k indices sorted by score, applying category filter if provided
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

        results = []
        for idx in top_indices:
            if len(results) >= top_k:
                break
            if scores[idx] <= 0:  # only return chunks with some match
                continue
            chunk = self.chunks[idx]
            # Apply category filter: skip chunks whose act_category does not match
            if category_filter is not None:
                chunk_cat = (
                    chunk.metadata.act_category.value
                    if chunk.metadata and chunk.metadata.act_category
                    else None
                )
                if chunk_cat != category_filter:
                    continue
            chunk = chunk.model_copy()
            chunk.score = float(scores[idx])
            results.append(chunk)

        return results

    def save_index(self) -> None:
        """Persist BM25 index to disk."""
        self.INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file and swap it in, so two workers starting at once
        # (make scale) can never leave a half-written index behind.
        tmp = self.INDEX_PATH.with_suffix(f".{os.getpid()}.tmp")
        with open(tmp, "wb") as f:
            pickle.dump(
                {
                    "tokenizer_version": self.TOKENIZER_VERSION,
                    "chunks": [c.model_dump(exclude={"embedding"}) for c in self.chunks],
                    "tokenized_corpus": self.tokenized_corpus,
                },
                f,
            )
        os.replace(tmp, self.INDEX_PATH)
        logger.info(f"BM25 index saved to {self.INDEX_PATH}")

    @classmethod
    def load_index(cls) -> "BM25Retriever":
        """Load BM25 index from disk."""
        if not cls.INDEX_PATH.exists():
            raise FileNotFoundError(
                f"BM25 index not found at {cls.INDEX_PATH}. Run ingestion first."
            )
        with open(cls.INDEX_PATH, "rb") as f:
            data = pickle.load(f)
        instance = cls()
        from src.models import Chunk

        instance.chunks = [Chunk(**c) for c in data["chunks"]]
        if data.get("tokenizer_version") == cls.TOKENIZER_VERSION:
            instance.tokenized_corpus = data["tokenized_corpus"]
        else:
            # Built by a different tokenizer: its tokens wouldn't match today's
            # queries. The chunk text is in the file, so re-tokenize and resave.
            logger.warning("BM25 index was built with an older tokenizer; re-tokenizing")
            instance.tokenized_corpus = [cls._tokenize(c.text) for c in instance.chunks]
            try:
                instance.save_index()
            except OSError as exc:
                # Read-only data (e.g. a container mount): keep serving from the
                # re-tokenized copy in memory and redo it on the next start.
                logger.warning(f"Couldn't save the re-tokenized BM25 index: {exc}")
        instance.bm25 = BM25Okapi(instance.tokenized_corpus)
        logger.info(f"BM25 index loaded: {len(instance.chunks)} chunks")
        return instance

    # Bump whenever _tokenize changes; older pickles are re-tokenized on load.
    TOKENIZER_VERSION = 2

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Unicode-aware lowercase tokenizer.

        Keeps Devanagari and other Indic scripts as well as digits, so Hindi
        queries and section numbers ("206") produce sparse matches. Must stay
        in sync with the pickled index — rebuild via scripts/rebuild_bm25.py
        after changing this.
        """
        import re

        # Letters and digits, plus the vowel signs and viramas of the Indic
        # blocks (U+0900-U+0DFF), which \w alone treats as word breaks and so
        # split "धारा" into "ध", "र". Dandas (U+0964-5) still separate words.
        return re.findall(r"(?:[^\W_]|[\u0900-\u0963\u0966-\u0DFF])+", text.lower())
