"""Rebuild the pickled BM25 index from data/processed/chunks.json.

Run this whenever the tokenizer in src/retrieval/sparse.py changes, or after
new documents are ingested outside the main pipeline:

    python scripts/rebuild_bm25.py

No re-embedding happens — the index stores tokenized text only.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.models import Chunk  # noqa: E402
from src.retrieval.sparse import BM25Retriever  # noqa: E402


def main() -> None:
    chunks_path = ROOT / "data/processed/chunks.json"
    print(f"Loading {chunks_path} ...")
    raw = json.loads(chunks_path.read_text())
    chunks = [Chunk(**c) for c in raw]
    print(f"Loaded {len(chunks)} chunks; building index ...")
    t0 = time.perf_counter()
    retriever = BM25Retriever(chunks)
    retriever.save_index()
    print(f"Rebuilt {BM25Retriever.INDEX_PATH} in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
