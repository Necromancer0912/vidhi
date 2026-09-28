"""
NyayaBot — Admin & Ingestion endpoints.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.main import app_state
from src.api.security import admin_secret, require_admin, secrets_match
from src.config import settings
from src.ingestion.chunker import LegalChunker
from src.ingestion.embedder import get_embedding_model
from src.ingestion.indexer import QdrantIndexer
from src.models import ActCategory, Chunk, ChunkMetadata

logger = logging.getLogger(__name__)
router = APIRouter()


class IngestTextRequest(BaseModel):
    project: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100000)
    category: str = Field(default="general")
    filename: Optional[str] = None
    secret: str


verify_stats_access = require_admin


def run_ingest_process(chunks: list[Chunk], qdrant_client, bm25_retriever) -> None:
    """
    Synchronous processing pipeline executed in a background thread:
    - Batch embeds chunks
    - Indexes to Qdrant
    - Rebuilds and saves the BM25 search index
    """
    # 2. Embed chunks in batches for speed
    embedder = get_embedding_model()
    texts_to_embed = [chunk.text for chunk in chunks]
    embeddings = embedder.embed_batch(texts_to_embed)
    for chunk, emb in zip(chunks, embeddings):
        chunk.embedding = emb

    # 3. Index to Qdrant
    indexer = QdrantIndexer(client=qdrant_client)
    indexer.setup_indexes()
    indexer.index_chunks(chunks)
    logger.info(f"Successfully indexed {len(chunks)} custom chunks to Qdrant")

    # 4. Rebuild & Save BM25 sparse index dynamically from Qdrant
    scroll_res = qdrant_client.scroll(
        collection_name=settings.qdrant_collection,
        limit=10000,
        with_payload=True,
        with_vectors=False,
    )[0]

    all_chunks = []
    for hit in scroll_res:
        payload = hit.payload or {}
        try:
            cat_val = ActCategory(payload.get("act_category", "general"))
        except (ValueError, KeyError):
            cat_val = ActCategory.GENERAL

        metadata = ChunkMetadata(
            source_url=payload.get("source_url") or payload.get("source") or "",
            document_title=payload.get("document_title") or payload.get("act_name") or "",
            section=payload.get("section") or "",
            act_category=cat_val,
            chunk_index=payload.get("chunk_index") or 0,
        )
        all_chunks.append(Chunk(id=hit.id, text=payload.get("text", ""), metadata=metadata))

    if all_chunks:
        bm25_retriever.build_index(all_chunks)
        bm25_retriever.save_index()
        logger.info(f"Rebuilt and saved BM25 index with {len(all_chunks)} chunks")


@router.get("/stats")
async def get_system_stats(access: bool = Depends(verify_stats_access)):
    """Query Qdrant and Redis to return database stats and project lists."""
    if not app_state.qdrant_client:
        raise HTTPException(status_code=500, detail="Qdrant connection not initialized")

    try:
        indexer = QdrantIndexer(client=app_state.qdrant_client)
        stats = indexer.get_stats()

        # Let's get unique project titles by scrolling Qdrant
        res = app_state.qdrant_client.scroll(
            collection_name=settings.qdrant_collection,
            limit=100,
            with_payload=True,
            with_vectors=False,
        )[0]
        projects = list(
            set(
                hit.payload.get("document_title")
                for hit in res
                if hit.payload and hit.payload.get("document_title")
            )
        )

        # Approximate total queries from today's routes count in Redis
        from src.cache.redis_store import get_analytics

        analytics = get_analytics()
        today_routes = analytics.get_dashboard().get("today_routes", {})
        total_queries = sum(int(v) for v in today_routes.values())

        return {
            "success": True,
            "vectorStore": {"totalChunks": stats["chunks"]},
            "queryLog": {"totalLogs": total_queries},
            "projects": projects,
        }
    except Exception as e:
        logger.error(f"Stats query error: {e}")
        raise HTTPException(status_code=500, detail="Couldn't load statistics")


@router.post("/ingest/text")
async def ingest_custom_text(request: IngestTextRequest):
    """Chunk, embed, and index a new text document into Qdrant and update BM25."""
    expected_secret = admin_secret()
    if not expected_secret:
        raise HTTPException(
            status_code=503,
            detail="Ingestion is disabled because ADMIN_SECRET is not configured in the server environment.",
        )
    if not secrets_match(request.secret, expected_secret):
        raise HTTPException(status_code=401, detail="Invalid admin secret")

    if not app_state.qdrant_client:
        raise HTTPException(status_code=500, detail="Qdrant connection not initialized")

    try:
        # 1. Chunk document
        chunker = LegalChunker(chunk_tokens=512, overlap_tokens=64)
        cat = (
            ActCategory(request.category)
            if request.category in [c.value for c in ActCategory]
            else ActCategory.GENERAL
        )

        source_url = f"file://{request.filename}" if request.filename else "uploaded://custom"

        chunks = chunker.chunk_document(
            text=request.text,
            source_url=source_url,
            document_title=request.project,
            act_category=cat,
            section="",
        )

        if not chunks:
            return {"success": False, "error": "No chunks generated"}

        # 2. Run embedding, indexing, and BM25 rebuilding in background thread
        await asyncio.to_thread(
            run_ingest_process, chunks, app_state.qdrant_client, app_state.bm25_retriever
        )

        return {
            "success": True,
            "message": f"Successfully chunked and indexed {len(chunks)} chunks into NyayaBot Knowledge Store.",
        }
    except Exception as e:
        logger.error(f"Custom ingestion error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ingestion failed; see server logs")
