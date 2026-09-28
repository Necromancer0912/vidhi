"""
NyayaBot — HyDE (Hypothetical Document Expansion) for query enrichment.
Generates a hypothetical answer paragraph, embeds it, uses it as a search vector.
This dramatically improves recall for legal queries where the user phrasing differs
from the language in the original legal documents.
"""
from __future__ import annotations

import logging

from src.ingestion.embedder import get_embedding_model

logger = logging.getLogger(__name__)

HYDE_PROMPT = """You are an expert in Indian law and government procedures.
Write a SHORT (3-4 sentence) hypothetical paragraph from an official Indian government document, 
legal act, or government guide that would perfectly answer the following citizen question.
Write ONLY the paragraph — no intro, no explanation, no quotation marks.
The paragraph should use formal legal/bureaucratic language as found in Indian government documents.

Citizen question: {query}

Hypothetical official document paragraph:"""


async def generate_hyde_query(query: str, llm) -> tuple[str, list[float]]:
    """
    Generate a hypothetical document for the query, then embed it.
    
    Returns:
        (hyde_text, hyde_embedding) — the generated text and its embedding vector
    """
    try:
        hyde_text = await llm.ainvoke(HYDE_PROMPT.format(query=query))
        if hasattr(hyde_text, "content"):
            hyde_text = hyde_text.content

        # Embed the hypothetical document
        embedder = get_embedding_model()
        hyde_embed = embedder.embed(str(hyde_text))

        logger.debug(f"HyDE generated: {str(hyde_text)[:100]}...")
        return str(hyde_text), hyde_embed

    except Exception as e:
        logger.warning(f"HyDE generation failed: {e} — using original query embedding")
        embedder = get_embedding_model()
        return query, embedder.embed(query)
