"""
NyayaBot — Full ingestion pipeline orchestrator.
Pipeline: static knowledge → chunk → embed (Ollama GPU) → index (Qdrant)

Usage:
  python -m src.ingestion.pipeline                 # static + scraping (~10 min)
  python -m src.ingestion.pipeline --skip-scraping # static only (~5 min)
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.ingestion.static_data import STATIC_KNOWLEDGE
from src.config import settings
from src.ingestion.chunker import LegalChunker
from src.ingestion.embedder import get_embedding_model
from src.ingestion.indexer import QdrantIndexer, get_qdrant_client
from src.models import ActCategory, Chunk, ChunkMetadata
from src.ingestion.loaders import DocumentLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Suppress noisy warnings from pdfminer and HTTP requests from httpx
logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _get_act_category(filename: str) -> ActCategory:
    """Map a PDF filename to its correct ActCategory based on keywords."""
    fn = filename.lower()
    if any(kw in fn for kw in ["motor_vehicle", "traffic", "cmv", "driving", "challan"]):
        return ActCategory.TRAFFIC_LAW
    elif any(kw in fn for kw in ["arnesh_kumar", "lalita_kumari", "dk_basu", "prakash_singh"]):
        return ActCategory.CRIMINAL_LAW
    elif any(kw in fn for kw in ["puttaswamy", "shreya_singhal", "kesavananda_bharati", "sr_bommai", "gian_kaur", "aruna_shanbaug", "selvi", "shayara_bano", "joseph_shine", "navtej_johar", "common_cause", "bandhua_mukti_morcha", "mc_mehta", "indra_sawhney"]):
        return ActCategory.CONSTITUTIONAL
    elif "vishaka" in fn:
        return ActCategory.LABOUR_LAW
    elif "constitution" in fn:
        return ActCategory.CONSTITUTIONAL
    elif any(kw in fn for kw in ["consumer_protection", "information_technology", "it_act", "personal_data", "dpdp", "e_commerce"]):
        return ActCategory.CONSUMER_RIGHTS
    elif any(kw in fn for kw in ["contract", "specific_relief", "limitation", "civil_procedure", "easements", "arbitration", "partition", "registration", "stamp", "transfer_of_property", "rent", "marriage", "divorce", "succession", "adoption", "maintenance", "minority", "guardianship", "ward", "shariat", "personal_law", "dowry"]):
        return ActCategory.CIVIL_LAW
    elif any(kw in fn for kw in ["bns", "bnss", "bsa", "penal_code", "criminal_procedure", "evidence", "pocso", "domestic_violence", "arms", "national_security", "corruption", "money_laundering", "unlawful_activities", "ndps", "extradition"]):
        return ActCategory.CRIMINAL_LAW
    elif any(kw in fn for kw in ["income_tax", "goods_and_services_tax"]):
        return ActCategory.TAX_LAW
    elif any(kw in fn for kw in ["companies", "partnership", "llp", "insolvency", "sale_of_goods", "securities", "designs", "trade_marks", "geographical", "competition", "fema"]):
        return ActCategory.CORPORATE_LAW
    elif any(kw in fn for kw in ["labour", "factories", "provident", "gratuity", "compensation", "bonus", "maternity", "posh", "wages", "disputes", "trade_union", "employee", "workmen"]):
        return ActCategory.LABOUR_LAW
    elif any(kw in fn for kw in ["real_estate", "rera"]):
        return ActCategory.REAL_ESTATE
    elif "right_to_information" in fn:
        return ActCategory.TRANSPARENCY_LAW
    elif any(kw in fn for kw in ["disaster", "food_security", "parents_and_senior_citizens", "transgender", "education", "rte", "sati", "disabilities", "wild_life", "forest"]):
        return ActCategory.SOCIAL_WELFARE
    return ActCategory.GENERAL


def ingest_static_knowledge(chunker: LegalChunker) -> list[Chunk]:
    """Convert the 10 hand-crafted legal knowledge entries into chunks."""
    logger.info(f"Ingesting {len(STATIC_KNOWLEDGE)} static knowledge entries")
    chunks = []
    for entry in STATIC_KNOWLEDGE:
        new_chunks = chunker.chunk_document(
            text=entry["text"],
            source_url=entry["url"],
            document_title=entry["title"],
            act_category=entry["category"],
            section=entry.get("section", ""),
        )
        chunks.extend(new_chunks)
        logger.info(f"  ✓ {entry['title']}: {len(new_chunks)} chunks")
    return chunks


def ingest_pdf_documents(chunker: LegalChunker) -> list[Chunk]:
    """Ingest downloaded PDF files like Bharatiya Nyaya Sanhita."""
    logger.info("Ingesting PDF documents from data directory...")
    chunks = []
    data_dir = Path("data/raw")
    if not data_dir.exists():
        return chunks

    for pdf_path in data_dir.glob("*.pdf"):
        logger.info(f"Loading PDF: {pdf_path.name}")
        try:
            full_text = DocumentLoader.load(pdf_path)
            if not full_text or len(full_text.strip()) == 0:
                logger.warning(f"  ⚠ Empty text extracted from {pdf_path.name}. Skipping.")
                continue
                
            category = _get_act_category(pdf_path.name)
            
            new_chunks = chunker.chunk_document(
                text=full_text,
                source_url=f"file://{pdf_path.name}",
                document_title=pdf_path.stem.replace("_", " "),
                act_category=category,
                section="",
            )
            chunks.extend(new_chunks)
            logger.info(f"  ✓ {pdf_path.name} [{category.value}]: {len(new_chunks)} chunks")
        except Exception as e:
            logger.error(f"  ✗ Failed to ingest {pdf_path.name}: {e}")
        
    return chunks


def ingest_situation_templates(chunker: LegalChunker) -> list[Chunk]:
    """Ingest custom situation template guide files from data/situations/ recursively."""
    logger.info("Ingesting situation templates from data/situations/...")
    chunks = []
    data_dir = Path("data/situations")
    if not data_dir.exists():
        return chunks

    for file_path in data_dir.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in (".md", ".txt"):
            logger.info(f"Loading situation template: {file_path.relative_to(data_dir)}")
            try:
                full_text = DocumentLoader.load(file_path)
                if not full_text or len(full_text.strip()) == 0:
                    continue
                
                # Title is the file name without extension, formatted nicely
                title = file_path.stem.replace("_", " ").title()
                
                new_chunks = chunker.chunk_document(
                    text=full_text,
                    source_url=f"file://situations/{file_path.relative_to(data_dir)}",
                    document_title=f"Situation Guide: {title}",
                    act_category=ActCategory.SITUATION_GUIDE,
                    section="",
                )
                chunks.extend(new_chunks)
                logger.info(f"  ✓ {file_path.name} [situation_guide]: {len(new_chunks)} chunks")
            except Exception as e:
                logger.error(f"  ✗ Failed to ingest situation template {file_path.name}: {e}")
    return chunks




# Live scrapers removed - PDFs are managed in data/raw/


def embed_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """
    Add embeddings to all chunks using Ollama (GPU if available).
    Falls back to sentence-transformers CPU if Ollama not available.
    """
    embedder = get_embedding_model()
    provider = "Ollama GPU" if embedder.is_available() else "CPU (sentence-transformers)"
    logger.info(f"Embedding {len(chunks)} chunks via {provider} [{embedder.model}]")

    batch_size = 64
    total = len(chunks)
    for i in tqdm(range(0, total, batch_size), desc="Embedding Batches"):
        batch = chunks[i : i + batch_size]
        batch_texts = [chunk.text for chunk in batch]
        batch_embeddings = embedder.embed_batch(batch_texts, batch_size=batch_size)
        for chunk, emb in zip(batch, batch_embeddings):
            chunk.embedding = emb

    return chunks


def save_chunks_to_disk(chunks: list[Chunk], output_path: Path) -> None:
    """Save chunks (without embeddings) to JSON for backup and inspection."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = []
    for chunk in chunks:
        d = chunk.model_dump()
        d.pop("embedding", None)  # don't save large float arrays
        data.append(d)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"Saved {len(chunks)} chunks to {output_path}")


def save_embedded_chunks_to_disk(chunks: list[Chunk], output_path: Path) -> None:
    """Save chunks (WITH embeddings) to JSON for transfer to another machine."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = [chunk.model_dump() for chunk in chunks]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"Saved {len(chunks)} embedded chunks to {output_path}")


def load_embedded_chunks_from_disk(input_path: Path) -> list[Chunk]:
    """Load chunks (WITH embeddings) from JSON."""
    if not input_path.exists():
        raise FileNotFoundError(f"Embedded chunks file not found at {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    chunks = [Chunk(**d) for d in data]
    logger.info(f"Loaded {len(chunks)} embedded chunks from {input_path}")
    return chunks


def run_ingestion(
    skip_scraping: bool = False,
    only_embed: bool = False,
    only_index: bool = False,
    only_parse: bool = False,
) -> None:
    """Full pipeline: static knowledge → chunk → embed → Qdrant index."""
    import gc
    start = time.time()
    logger.info("=" * 60)
    logger.info("NyayaBot Ingestion Pipeline Starting (Memory-Safe)")
    logger.info(f"  Only Parse: {only_parse}")
    logger.info(f"  Only Embed: {only_embed}")
    logger.info(f"  Only Index: {only_index}")
    logger.info(f"  Qdrant:     {settings.qdrant_url}")
    logger.info(f"  Embed:      {settings.ollama_embed_model} via Ollama")
    logger.info("=" * 60)

    embedded_chunks: list[Chunk] = []

    if only_index:
        # ── Load Pre-Computed Embedded Chunks ─────────────────────────────────
        embedded_chunks = load_embedded_chunks_from_disk(Path("data/processed/embedded_chunks.json"))
    else:
        pdf_dir = Path("data/raw")
        pdf_paths = sorted(list(pdf_dir.glob("*.pdf"))) if pdf_dir.exists() else []

        # ── Phase 0: Text Extraction & Disk Caching ───────────────────────────
        if pdf_paths:
            logger.info(f"--- Phase 0: Extracting text from {len(pdf_paths)} PDFs to disk cache ---")
            for idx, pdf_path in enumerate(pdf_paths):
                cache_file = Path("data/extracted_text") / f"{pdf_path.name}.txt"
                if cache_file.exists():
                    logger.info(f"[{idx+1}/{len(pdf_paths)}] Already extracted: {pdf_path.name}")
                    continue
                
                logger.info(f"[{idx+1}/{len(pdf_paths)}] Extracting: {pdf_path.name}...")
                try:
                    # DocumentLoader.load automatically caches text to data/extracted_text/
                    text_extracted = DocumentLoader.load(pdf_path)
                    logger.info(f"  ✓ Extracted and cached {len(text_extracted)} chars")
                    del text_extracted
                except Exception as e:
                    logger.error(f"  ✗ Failed to extract {pdf_path.name}: {e}")
                
                gc.collect()

        if only_parse:
            logger.info("Only parsing requested. Exiting after text extraction.")
            elapsed = time.time() - start
            logger.info("=" * 60)
            logger.info(f"✅ Ingestion parsing complete in {elapsed:.1f}s ({elapsed/60:.1f} min)")
            logger.info("=" * 60)
            return

        # Create cache directory for individual file checkpoints
        cache_dir = Path("data/processed/chunks_cache")
        cache_dir.mkdir(parents=True, exist_ok=True)

        chunker = LegalChunker(chunk_tokens=256, overlap_tokens=32)
        seen = set()

        # ── 1. Static Knowledge ───────────────────────────────────────────────
        static_cache_path = cache_dir / "static_knowledge.json"
        static_chunks: list[Chunk] = []
        if static_cache_path.exists():
            logger.info("Loading cached static knowledge chunks...")
            try:
                with open(static_cache_path, "r", encoding="utf-8") as f:
                    static_data = json.load(f)
                static_chunks = [Chunk(**d) for d in static_data]
                for chunk in static_chunks:
                    seen.add(hash(chunk.text[:200]))
                logger.info(f"  ✓ Loaded {len(static_chunks)} static chunks from cache")
            except Exception as e:
                logger.error(f"  ⚠ Failed to load cached static knowledge chunks: {e}. Re-processing.")
                static_cache_path.unlink(missing_ok=True)

        if not static_cache_path.exists():
            raw_static_chunks = ingest_static_knowledge(chunker)
            unique_static_chunks = []
            for chunk in raw_static_chunks:
                key = hash(chunk.text[:200])
                if key not in seen:
                    seen.add(key)
                    unique_static_chunks.append(chunk)
            if unique_static_chunks:
                logger.info(f"Embedding {len(unique_static_chunks)} unique static chunks...")
                static_chunks = embed_chunks(unique_static_chunks)
                # Save to cache
                with open(static_cache_path, "w", encoding="utf-8") as f:
                    json.dump([c.model_dump() for c in static_chunks], f, indent=2, ensure_ascii=False, default=str)
                logger.info("  ✓ Saved embedded static chunks to cache")
            del raw_static_chunks, unique_static_chunks
            gc.collect()

        # ── 2. Situation Templates ────────────────────────────────────────────
        situations_cache_path = cache_dir / "situations_knowledge.json"
        situations_chunks: list[Chunk] = []
        if situations_cache_path.exists():
            logger.info("Loading cached situation template chunks...")
            try:
                with open(situations_cache_path, "r", encoding="utf-8") as f:
                    situations_data = json.load(f)
                situations_chunks = [Chunk(**d) for d in situations_data]
                for chunk in situations_chunks:
                    seen.add(hash(chunk.text[:200]))
                logger.info(f"  ✓ Loaded {len(situations_chunks)} situation chunks from cache")
            except Exception as e:
                logger.error(f"  ⚠ Failed to load cached situation chunks: {e}. Re-processing.")
                situations_cache_path.unlink(missing_ok=True)

        if not situations_cache_path.exists():
            raw_situations_chunks = ingest_situation_templates(chunker)
            unique_situations_chunks = []
            for chunk in raw_situations_chunks:
                key = hash(chunk.text[:200])
                if key not in seen:
                    seen.add(key)
                    unique_situations_chunks.append(chunk)
            if unique_situations_chunks:
                logger.info(f"Embedding {len(unique_situations_chunks)} unique situation chunks...")
                situations_chunks = embed_chunks(unique_situations_chunks)
                # Save to cache
                with open(situations_cache_path, "w", encoding="utf-8") as f:
                    json.dump([c.model_dump() for c in situations_chunks], f, indent=2, ensure_ascii=False, default=str)
                logger.info("  ✓ Saved embedded situation chunks to cache")
            del raw_situations_chunks, unique_situations_chunks
            gc.collect()

        # ── 3. PDF Documents (File-by-File Chunk & Embed) ─────────────────────
        if pdf_paths:
            logger.info(f"--- Phase 1: Chunking and Embedding {len(pdf_paths)} PDFs ---")
            
            for idx, pdf_path in enumerate(pdf_paths):
                pdf_cache_path = cache_dir / f"{pdf_path.name}.json"
                
                # Check if this PDF is already processed and cached
                if pdf_cache_path.exists():
                    logger.info(f"[{idx+1}/{len(pdf_paths)}] Loading cached chunks for {pdf_path.name}...")
                    try:
                        with open(pdf_cache_path, "r", encoding="utf-8") as f:
                            pdf_data = json.load(f)
                        cached_pdf_chunks = [Chunk(**d) for d in pdf_data]
                        for chunk in cached_pdf_chunks:
                            seen.add(hash(chunk.text[:200]))
                        logger.info(f"  ✓ Loaded {len(cached_pdf_chunks)} chunks from cache")
                        del cached_pdf_chunks
                    except Exception as e:
                        logger.error(f"  ⚠ Failed to load cache for {pdf_path.name}: {e}. Will re-process.")
                        pdf_cache_path.unlink(missing_ok=True)
                
                # If not cached or failed to load, process it now
                if not pdf_cache_path.exists():
                    logger.info(f"[{idx+1}/{len(pdf_paths)}] Chunking & Embedding: {pdf_path.name}")
                    try:
                        # Will load instantly from disk cache data/extracted_text/
                        full_text = DocumentLoader.load(pdf_path)
                        if not full_text or len(full_text.strip()) == 0:
                            logger.warning(f"  ⚠ Empty text extracted from {pdf_path.name}. Skipping.")
                            with open(pdf_cache_path, "w", encoding="utf-8") as f:
                                json.dump([], f)
                            continue
                            
                        category = _get_act_category(pdf_path.name)
                        
                        file_chunks = chunker.chunk_document(
                            text=full_text,
                            source_url=f"file://{pdf_path.name}",
                            document_title=pdf_path.stem.replace("_", " "),
                            act_category=category,
                            section="",
                        )
                        
                        # Deduplicate on-the-fly
                        unique_file_chunks = []
                        for chunk in file_chunks:
                            key = hash(chunk.text[:200])
                            if key not in seen:
                                seen.add(key)
                                unique_file_chunks.append(chunk)
                                
                        if unique_file_chunks:
                            logger.info(f"  Embedding {len(unique_file_chunks)} chunks for {pdf_path.name}...")
                            embedded_file_chunks = embed_chunks(unique_file_chunks)
                            # Save to cache
                            with open(pdf_cache_path, "w", encoding="utf-8") as f:
                                json.dump([c.model_dump() for c in embedded_file_chunks], f, indent=2, ensure_ascii=False, default=str)
                            logger.info(f"  ✓ Saved {len(embedded_file_chunks)} embedded chunks to cache")
                        else:
                            with open(pdf_cache_path, "w", encoding="utf-8") as f:
                                json.dump([], f)
                            logger.info(f"  ✓ Processed: 0 new chunks (all duplicates)")
                            
                    except Exception as e:
                        logger.error(f"  ✗ Failed to process {pdf_path.name}: {e}", exc_info=True)
                    
                    # Force garbage collection to free RAM
                    if 'full_text' in locals():
                        del full_text
                    if 'file_chunks' in locals():
                        del file_chunks
                    if 'unique_file_chunks' in locals():
                        del unique_file_chunks
                    if 'embedded_file_chunks' in locals():
                        del embedded_file_chunks
                    gc.collect()
        
        # ── 3. Merge All Checkpoints ──────────────────────────────────────────
        logger.info("Merging all cache checkpoints into final embedded_chunks.json...")
        embedded_chunks = []
        
        # Merge static knowledge
        if static_cache_path.exists():
            try:
                with open(static_cache_path, "r", encoding="utf-8") as f:
                    static_data = json.load(f)
                embedded_chunks.extend([Chunk(**d) for d in static_data])
            except Exception as e:
                logger.error(f"Failed to merge static knowledge cache: {e}")

        # Merge situation template knowledge
        if situations_cache_path.exists():
            try:
                with open(situations_cache_path, "r", encoding="utf-8") as f:
                    situations_data = json.load(f)
                embedded_chunks.extend([Chunk(**d) for d in situations_data])
            except Exception as e:
                logger.error(f"Failed to merge situation template cache: {e}")
            
        # Merge PDF chunks
        for cache_file_path in sorted(list(cache_dir.glob("*.pdf.json"))):
            logger.info(f"Merging cached chunks from {cache_file_path.name}...")
            try:
                with open(cache_file_path, "r", encoding="utf-8") as f:
                    pdf_data = json.load(f)
                embedded_chunks.extend([Chunk(**d) for d in pdf_data])
            except Exception as e:
                logger.error(f"Failed to merge cache for {cache_file_path.name}: {e}")
            
        logger.info(f"Total merged chunks: {len(embedded_chunks)}")

        # ── 4. Save Backup Chunks WITH & WITHOUT Embeddings ───────────────────
        save_embedded_chunks_to_disk(embedded_chunks, Path("data/processed/embedded_chunks.json"))
        save_chunks_to_disk(embedded_chunks, Path("data/processed/chunks.json"))

    # ── 5. Build and save BM25 Index ──────────────────────────────────────────
    from src.retrieval.sparse import BM25Retriever
    logger.info("Building and saving BM25 sparse index...")
    bm25 = BM25Retriever(embedded_chunks)
    bm25.save_index()

    if only_embed:
        logger.info("Only embedding requested. Exiting without indexing to Qdrant.")
        elapsed = time.time() - start
        logger.info("=" * 60)
        logger.info(f"✅ Ingestion embedding complete in {elapsed:.1f}s ({elapsed/60:.1f} min)")
        logger.info("=" * 60)
        return

    # ── 6. Index to Qdrant ────────────────────────────────────────────────────
    logger.info("Connecting to Qdrant...")
    client = get_qdrant_client()
    indexer = QdrantIndexer(client=client)

    logger.info("Setting up collection...")
    indexer.setup_indexes()

    logger.info(f"Indexing {len(embedded_chunks)} chunks into Qdrant...")
    indexed = indexer.index_chunks(embedded_chunks, batch_size=100)

    stats = indexer.get_stats()

    # ── 7. Summary ────────────────────────────────────────────────────────────
    elapsed = time.time() - start
    logger.info("=" * 60)
    logger.info(f"✅ Ingestion complete in {elapsed:.1f}s ({elapsed/60:.1f} min)")
    logger.info(f"   Chunks indexed: {indexed}")
    logger.info(f"   Qdrant stats:   {stats['chunks']} chunks, {stats['documents']} documents")
    logger.info("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NyayaBot ingestion pipeline")
    parser.add_argument(
        "--skip-scraping",
        action="store_true",
        help="Deprecated: live scraping is removed. This flag has no effect.",
    )
    parser.add_argument(
        "--only-parse",
        action="store_true",
        help="Only extract and cache text from PDFs to disk. Do not chunk or embed.",
    )
    parser.add_argument(
        "--only-embed",
        action="store_true",
        help="Only chunk and embed, saving to disk. Do not connect/index to Qdrant.",
    )
    parser.add_argument(
        "--only-index",
        action="store_true",
        help="Only load pre-embedded chunks from disk and index them to Qdrant.",
    )
    args = parser.parse_args()
    
    # Check mutual exclusivity
    modes = sum([bool(args.only_parse), bool(args.only_embed), bool(args.only_index)])
    if modes > 1:
        logger.error("Cannot specify more than one of --only-parse, --only-embed, and --only-index!")
        sys.exit(1)
        
    run_ingestion(
        skip_scraping=args.skip_scraping,
        only_embed=args.only_embed,
        only_index=args.only_index,
        only_parse=args.only_parse,
    )
