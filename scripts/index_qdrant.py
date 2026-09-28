import sys
import os
import json
from pathlib import Path

# Add current working directory to path
sys.path.insert(0, os.getcwd())

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from rag import config

def main():
    embedded_file = Path("data/processed/embedded_chunks.json")
    if not embedded_file.exists():
        print(f"Error: Embedded chunks file not found at {embedded_file}.")
        print("Please run ingestion with '--only-embed' on the GPU PC first, then copy the file here.")
        sys.exit(1)

    print(f"Loading embedded chunks from {embedded_file}...")
    with open(embedded_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"Loaded {len(data)} chunks.")

    print(f"Connecting to Qdrant at {config.QDRANT_URL}...")
    try:
        client = QdrantClient(url=config.QDRANT_URL)
        
        # 1. Ensure collection exists
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]
        
        target_collection = config.QDRANT_COLLECTION
        if target_collection not in collection_names:
            print(f"Creating collection '{target_collection}' with dim={config.EMBED_DIM}...")
            client.create_collection(
                collection_name=target_collection,
                vectors_config=VectorParams(size=config.EMBED_DIM, distance=Distance.COSINE)
            )
            print("✓ Collection created.")
        else:
            print(f"✓ Collection '{target_collection}' already exists.")

        # 2. Upload points in batches
        print("Uploading points to Qdrant...")
        points = []
        for idx, item in enumerate(data):
            chunk_id = item.get("id")
            embedding = item.get("embedding")
            text = item.get("text", "")
            meta = item.get("metadata", {})
            
            if not embedding:
                print(f"  ⚠ Skipping chunk {chunk_id}: No embedding found")
                continue
                
            # Flatten/align metadata for Qdrant payload search
            payload = {
                "text": text,
                "source_url": meta.get("source_url", ""),
                "document_title": meta.get("document_title", ""),
                "section": meta.get("section", ""),
                "act_category": meta.get("act_category", "general"),
                "chunk_index": meta.get("chunk_index", 0),
                "page_number": meta.get("page_number", 0)
            }
            
            points.append(PointStruct(
                id=chunk_id,
                vector=embedding,
                payload=payload
            ))

        # Upload in batches of 100
        batch_size = 100
        total_uploaded = 0
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            client.upsert(
                collection_name=target_collection,
                points=batch
            )
            total_uploaded += len(batch)
            print(f"  Uploaded {total_uploaded}/{len(points)} points...")

        print(f"✓ Success! Indexed {total_uploaded} chunks into Qdrant collection '{target_collection}'.")
    except Exception as e:
        print(f"Error during Qdrant indexing: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
