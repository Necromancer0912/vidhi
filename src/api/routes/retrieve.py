"""
NyayaBot — /retrieve endpoint (direct chunk retrieval for testing/debugging).
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from src.api.main import app_state
from src.api.security import require_admin
from src.models import RetrieveRequest, RetrieveResponse
from src.retrieval.fusion import reciprocal_rank_fusion
from src.retrieval.reranker import get_reranker

router = APIRouter()


@router.post("/retrieve", response_model=RetrieveResponse, dependencies=[Depends(require_admin)])
async def retrieve_endpoint(request: RetrieveRequest):
    """
    Direct retrieval endpoint — returns top-k chunks for a query.
    Use this to test and benchmark retrieval quality independently.
    """
    start = time.time()

    # Dense retrieval
    dense = await app_state.dense_retriever.retrieve(
        query=request.query,
        top_k=20,
        category_filter=request.category_filter,
    )

    # Sparse (BM25) — apply same category filter as dense for consistent results
    sparse = app_state.bm25_retriever.retrieve(
        query=request.query,
        top_k=20,
        category_filter=request.category_filter,
    )

    # Fuse
    fused = reciprocal_rank_fusion(dense, sparse)

    # Re-rank to top_k
    reranker = get_reranker()
    reranked = reranker.rerank(request.query, fused, top_k=request.top_k)

    elapsed_ms = (time.time() - start) * 1000

    return RetrieveResponse(
        chunks=reranked,
        query=request.query,
        retrieval_time_ms=round(elapsed_ms, 1),
    )
