"""
NyayaBot — Qdrant dense retriever.
"""
from __future__ import annotations

import logging
from typing import Optional

from src.config import settings
from src.models import Chunk, ChunkMetadata, ActCategory

logger = logging.getLogger(__name__)


from qdrant_client import QdrantClient

class DenseRetriever:
    """
    Semantic (vector) retrieval from Qdrant.
    """

    def __init__(self, client: Optional[QdrantClient] = None):
        if client is None:
            client = QdrantClient(url=settings.qdrant_url)
        self.client = client

    async def retrieve(
        self,
        query: Optional[str] = None,
        top_k: int = 20,
        query_vector: Optional[list[float]] = None,
        category_filter: Optional[str] = None,
    ) -> list[Chunk]:
        """Vector similarity search in Qdrant."""
        embedding = query_vector
        if embedding is None and query is not None:
            from src.ingestion.embedder import get_embedding_model
            embedding = get_embedding_model().embed(query)

        if embedding is None:
            raise ValueError("Must provide either query or query_vector")

        import asyncio

        query_filter = None
        if category_filter:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="act_category",
                        match=MatchValue(value=category_filter)
                    )
                ]
            )

        def _search():
            return self.client.query_points(
                collection_name=settings.qdrant_collection,
                query=embedding,
                limit=top_k,
                query_filter=query_filter,
            ).points

        try:
            results = await asyncio.to_thread(_search)
        except Exception as e:
            logger.error(f"Qdrant retrieve error: {e}")
            return []

        chunks = []
        for hit in results:
            payload = hit.payload or {}
            try:
                cat = ActCategory(payload.get("act_category", "general"))
            except (ValueError, KeyError):
                cat = ActCategory.GENERAL

            chunks.append(
                Chunk(
                    id=hit.id,
                    text=payload.get("text", ""),
                    metadata=ChunkMetadata(
                        chunk_id=hit.id,
                        source_url=payload.get("source_url") or payload.get("source") or "",
                        document_title=payload.get("document_title") or payload.get("act_name") or "",
                        section=payload.get("section") or "",
                        act_category=cat,
                        chunk_index=payload.get("chunk_index") or 0,
                    ),
                    score=float(hit.score),
                    embedding=None,
                )
            )
        return chunks


