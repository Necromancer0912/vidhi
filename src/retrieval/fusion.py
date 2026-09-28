"""
NyayaBot — Reciprocal Rank Fusion (RRF) for combining dense + sparse results.
"""
from __future__ import annotations

from src.models import Chunk


def reciprocal_rank_fusion(
    dense_results: list[Chunk],
    sparse_results: list[Chunk],
    k: int = 60,
    dense_weight: float = 0.6,
    sparse_weight: float = 0.4,
) -> list[Chunk]:
    """
    Combine dense and sparse results using weighted RRF.
    
    Args:
        dense_results: Chunks from vector similarity search
        sparse_results: Chunks from BM25
        k: RRF constant (60 is standard; higher = less aggressive rank discounting)
        dense_weight: Weight multiplier for dense ranks (typically higher)
        sparse_weight: Weight multiplier for sparse/BM25 ranks
    
    Returns:
        Merged and re-ranked list of unique chunks, scored by RRF.
    """
    # Map chunk_id → chunk (keep the one with higher original score for payload)
    chunk_map: dict[str, Chunk] = {}

    for chunk in dense_results:
        if chunk.id not in chunk_map or chunk.score > chunk_map[chunk.id].score:
            chunk_map[chunk.id] = chunk

    for chunk in sparse_results:
        if chunk.id not in chunk_map:
            chunk_map[chunk.id] = chunk

    # Calculate RRF scores
    rrf_scores: dict[str, float] = {}

    for rank, chunk in enumerate(dense_results):
        rrf_scores[chunk.id] = rrf_scores.get(chunk.id, 0.0) + dense_weight / (k + rank + 1)

    for rank, chunk in enumerate(sparse_results):
        rrf_scores[chunk.id] = rrf_scores.get(chunk.id, 0.0) + sparse_weight / (k + rank + 1)

    # Sort by RRF score (descending)
    sorted_ids = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)

    # Return chunks with updated scores
    result = []
    for cid in sorted_ids:
        chunk = chunk_map[cid].model_copy()
        chunk.score = rrf_scores[cid]
        result.append(chunk)

    return result
