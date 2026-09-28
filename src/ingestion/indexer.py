"""
NyayaBot — Qdrant indexer.
"""
from __future__ import annotations

import logging
from typing import Optional

from src.config import settings
from src.models import Chunk

logger = logging.getLogger(__name__)


def get_async_qdrant_client():
    from qdrant_client import AsyncQdrantClient
    return AsyncQdrantClient(url=settings.qdrant_url)


def get_qdrant_client():
    from qdrant_client import QdrantClient
    return QdrantClient(url=settings.qdrant_url)



class QdrantIndexer:
    """
    Indexes legal chunks into Qdrant.
    """
    def __init__(self, client=None):
        self.client = client or get_qdrant_client()

    def setup_indexes(self):
        """Ensure collection and payload indexes exist in Qdrant."""
        from qdrant_client.models import Distance, PayloadSchemaType, VectorParams
        collections = self.client.get_collections().collections
        collection_names = [c.name for c in collections]
        if settings.qdrant_collection not in collection_names:
            logger.info(f"Creating collection '{settings.qdrant_collection}' in Qdrant...")
            self.client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE)
            )
        # Keyword index so act_category filters don't scan the full collection.
        schema = self.client.get_collection(settings.qdrant_collection).payload_schema or {}
        if "act_category" not in schema:
            self.client.create_payload_index(
                collection_name=settings.qdrant_collection,
                field_name="act_category",
                field_schema=PayloadSchemaType.KEYWORD,
            )
            logger.info("Created act_category payload index")

    def index_chunks(self, chunks: list[Chunk], batch_size: int = 100) -> int:
        """Upload chunks to Qdrant in batches."""
        from qdrant_client.models import PointStruct
        points = []
        for c in chunks:
            if not c.embedding:
                logger.warning(f"Chunk {c.id} has no embedding — skipping")
                continue
            
            payload = {
                "text": c.text,
                "source_url": c.metadata.source_url or "",
                "document_title": c.metadata.document_title or "",
                "section": c.metadata.section or "",
                "act_category": c.metadata.act_category.value if c.metadata.act_category else "general",
                "chunk_index": c.metadata.chunk_index or 0,
            }
            points.append(PointStruct(
                id=c.id,
                vector=c.embedding,
                payload=payload
            ))

        total = 0
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            self.client.upsert(
                collection_name=settings.qdrant_collection,
                points=batch
            )
            total += len(batch)
            logger.info(f"  Indexed {total}/{len(points)} chunks into Qdrant")
        return total

    def get_stats(self) -> dict:
        """Return Qdrant stats."""
        try:
            res = self.client.get_collection(collection_name=settings.qdrant_collection)
            scroll_res = self.client.scroll(
                collection_name=settings.qdrant_collection,
                limit=100,
                with_payload=True,
                with_vectors=False
            )[0]
            docs = set(hit.payload.get("document_title") for hit in scroll_res if hit.payload)
            return {
                "chunks": res.points_count,
                "documents": len(docs)
            }
        except Exception as e:
            logger.error(f"Error getting Qdrant stats: {e}")
            return {"chunks": 0, "documents": 0}

    def close(self):
        pass



