"""
NyayaBot — Critic Agent (the core differentiator).

Self-correction loop:
1. Extract atomic factual claims from generated answer
2. Score each claim against retrieved chunks via cosine similarity
3. If >2 claims score below threshold → flag and trigger query refinement + retry
4. Surface confidence score to user on final answer

KEY DESIGN PRINCIPLE: We do NOT ask the same LLM "is this answer correct?" 
(that leads to sycophantic self-evaluation). Instead we decompose the answer into 
atomic claims and score each one independently using cosine similarity against 
the actual retrieved documents. This gives us a NUMERIC grounding score we can 
log, threshold, and improve.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

import numpy as np

from src.config import settings
from src.ingestion.embedder import get_embedding_model
from src.models import ActCategory, Claim, Chunk, CriticResult

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Claim extraction prompt
# ─────────────────────────────────────────────
CLAIM_EXTRACTOR_PROMPT = """Extract all atomic factual claims from the following legal answer.
Each claim should be:
- A single, self-contained verifiable statement
- Specific enough to be checked against a document (not vague)
- Focused on facts, numbers, procedures, or legal provisions
- Inclusive of any timeline, year, or amendment assertions (e.g. "the 2018 amendment changed the threshold", "the 2026 amendment received assent on 6 April 2026")

Do NOT include: greetings, caveats, recommendations to consult a lawyer (these are not factual claims).

Return ONLY valid JSON in this exact format:
{{"claims": ["claim 1", "claim 2", "claim 3"]}}

Answer to analyze:
{answer}"""

# ─────────────────────────────────────────────
# Query refiner prompt (for retry)
# ─────────────────────────────────────────────
QUERY_REFINER_PROMPT = """The following atomic claims from a legal answer could NOT be grounded 
in the retrieved documents (low confidence):

Ungrounded claims:
{failed_claims}

Original user query:
{original_query}

These claims were NOT found in the documents, suggesting the retrieval missed relevant information.
Rewrite the search query to specifically target the missing information.
Add specific legal keywords, section numbers, or terminology that would help find the relevant provisions.
Return ONLY the refined query string — nothing else."""


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two normalized vectors."""
    a = np.array(vec_a)
    b = np.array(vec_b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


async def extract_claims(answer: str, llm) -> list[str]:
    """Decompose answer into atomic factual claims using LLM."""
    try:
        response = await llm.ainvoke(
            CLAIM_EXTRACTOR_PROMPT.format(answer=answer)
        )
        content = response.content if hasattr(response, "content") else str(response)

        # Extract JSON
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            claims = data.get("claims", [])
            if isinstance(claims, list) and all(isinstance(c, str) for c in claims):
                logger.debug(f"Extracted {len(claims)} claims from answer")
                return claims[:8]  # cap at 8 — enough to detect hallucination, avoids 60s embed freeze

    except Exception as e:
        logger.warning(f"Claim extraction failed: {e}")

    # Fallback: split answer into sentences as approximate claims
    sentences = re.split(r"[.!?]\s+", answer)
    return [s.strip() for s in sentences if len(s.strip()) > 30][:6]  # cap lower for fallback


def score_claims(claims: list[str], chunks: list[Chunk]) -> list[Claim]:
    """
    Score each claim against retrieved chunks using cosine similarity.
    
    For each claim, embed it and find the max cosine similarity across all chunks.
    Score < threshold → claim is likely hallucinated (not grounded in docs).
    """
    embedder = get_embedding_model()

    # Pre-compute chunk embeddings if not already available
    missing_indices = [idx for idx, c in enumerate(chunks) if not c.embedding]
    if missing_indices:
        missing_texts = [chunks[idx].text for idx in missing_indices]
        try:
            missing_embeddings = embedder.embed_batch(missing_texts)
            for idx, emb in zip(missing_indices, missing_embeddings):
                chunks[idx].embedding = emb
        except Exception as e:
            logger.warning(f"Batch embedding missing chunks failed: {e}")

    chunk_embeddings = []
    for chunk in chunks:
        if chunk.embedding:
            chunk_embeddings.append(chunk.embedding)
        else:
            chunk_embeddings.append(embedder.embed(chunk.text))

    # Batch embed all claims in a single call
    try:
        claim_embeddings = embedder.embed_batch(claims)
    except Exception as e:
        logger.warning(f"Batch embedding claims failed: {e}")
        claim_embeddings = [None] * len(claims)

    scored_claims = []
    for i, claim_text in enumerate(claims):
        try:
            claim_embed = claim_embeddings[i] if i < len(claim_embeddings) else None
            if claim_embed is None:
                claim_embed = embedder.embed(claim_text)

            similarities = [cosine_similarity(claim_embed, ce) for ce in chunk_embeddings]
            max_score = max(similarities) if similarities else 0.0
            best_chunk_idx = similarities.index(max_score) if similarities else 0

            # Temporal integrity verification: prevent hallucinated years
            years = re.findall(r"\b(19\d{2}|20\d{2})\b", claim_text)
            if years and chunks:
                is_negative_claim = any(
                    neg in claim_text.lower()
                    for neg in ["no ", "not ", "does not", "cannot", "no longer", "isn't", "lack of", "refuses", "without find", "excluding"]
                )
                if not is_negative_claim:
                    for year in years:
                        # Check if year is in the best matching chunk or any chunk
                        best_chunk = chunks[best_chunk_idx]
                        best_text = (best_chunk.text + " " + best_chunk.metadata.document_title).lower()
                        if year not in best_text:
                            in_any_chunk = False
                            for chunk in chunks:
                                chunk_text_full = (chunk.text + " " + chunk.metadata.document_title).lower()
                                if year in chunk_text_full:
                                    in_any_chunk = True
                                    break
                            if not in_any_chunk:
                                logger.info(
                                    f"Temporal verification failed: Claim mentions year '{year}' but it is not "
                                    f"present in any retrieved chunk. Penalizing score to 0.0."
                                )
                                max_score = 0.0
                                break

            claim = Claim(
                text=claim_text,
                grounding_score=max_score,
                is_grounded=max_score >= settings.critic_threshold,
                best_matching_chunk_id=chunks[best_chunk_idx].id if chunks else "",
            )
            scored_claims.append(claim)
            logger.debug(f"Claim score {max_score:.3f}: {claim_text[:60]}...")

        except Exception as e:
            logger.warning(f"Claim scoring failed for '{claim_text[:40]}': {e}")
            scored_claims.append(Claim(
                text=claim_text,
                grounding_score=0.0,
                is_grounded=False,
            ))

    return scored_claims


def compute_overall_confidence(scored_claims: list[Claim]) -> float:
    """
    Compute a single 0-1 confidence score for the entire answer.
    Uses weighted average: recent claims weighted slightly higher (end of answer matters).
    """
    if not scored_claims:
        return 0.5  # uncertain

    scores = [c.grounding_score for c in scored_claims]
    weights = [1 + (i / len(scores)) * 0.2 for i in range(len(scores))]  # slight recency bias
    weighted_avg = sum(s * w for s, w in zip(scores, weights)) / sum(weights)
    return round(weighted_avg, 3)


def calculate_legal_standing_score(claims: list[Claim], chunks: list[Chunk]) -> float:
    """
    Compute a user-facing legal standing score from 0.0 to 100.0.
    - Base score is the percentage of grounded claims.
    - Grounded claims are weighted based on source authority:
      * Supreme Court / Case Law: 1.0
      * Central Acts / Rules: 0.85
      * State Acts / Rules: 0.75
      * General Legal Knowledge (fallback): 0.5 (or 0.0 if not grounded)
    """
    if not claims:
        return 0.0

    total_weight = 0.0
    grounded_weight = 0.0

    chunk_map = {c.id: c for c in chunks}

    for claim in claims:
        claim_weight = 1.0
        total_weight += claim_weight

        if claim.is_grounded:
            matched_chunk = chunk_map.get(claim.best_matching_chunk_id)
            if matched_chunk:
                cat = matched_chunk.metadata.act_category
                # Adjust weight multiplier based on authority
                doc_title_lower = matched_chunk.metadata.document_title.lower()
                if (
                    cat == ActCategory.CONSTITUTIONAL
                    or "judgment" in doc_title_lower
                    or "vs" in doc_title_lower
                    or "court" in doc_title_lower
                ):
                    authority_multiplier = 1.0
                elif cat in [
                    ActCategory.TRAFFIC_LAW,
                    ActCategory.CONSUMER_RIGHTS,
                    ActCategory.LABOUR_LAW,
                    ActCategory.CRIMINAL_LAW,
                    ActCategory.CIVIL_LAW,
                    ActCategory.TAX_LAW,
                    ActCategory.CORPORATE_LAW,
                    ActCategory.REAL_ESTATE,
                    ActCategory.TRANSPARENCY_LAW,
                ]:
                    authority_multiplier = 0.85
                elif cat == ActCategory.SOCIAL_WELFARE:
                    authority_multiplier = 0.75
                else:
                    authority_multiplier = 0.65
            else:
                authority_multiplier = 0.5
            
            grounded_weight += claim_weight * authority_multiplier
        else:
            # Ungrounded claim adds 0 weight
            pass

    if total_weight == 0.0:
        return 0.0
    
    score = (grounded_weight / total_weight) * 100.0
    return round(score, 1)


async def critique_answer(
    answer: str,
    chunks: list[Chunk],
    llm,
    timeout_seconds: int = 25,  # hard timeout: if critic takes >25s, pass the answer through
) -> CriticResult:
    """
    Full critic pipeline with hard timeout.
    1. Extract atomic claims from answer
    2. Score each claim via cosine sim against chunks
    3. Determine if retry is needed
    4. Return CriticResult with confidence and failed claims

    If the entire pipeline takes > timeout_seconds, we return a passing result
    (confidence=0.7, no retry) so the user is never stuck on 'Verifying accuracy...' forever.
    """
    try:
        result = await asyncio.wait_for(
            _critique_answer_inner(answer, chunks, llm),
            timeout=timeout_seconds,
        )
        return result
    except asyncio.TimeoutError:
        logger.warning(
            f"Critic timed out after {timeout_seconds}s — passing answer through (no retry)"
        )
        return CriticResult(
            claims=[],
            overall_confidence=0.7,   # neutral pass — answer shown to user as-is
            needs_retry=False,
            failed_claims=[],
            legal_standing_score=50.0,
        )


async def _critique_answer_inner(
    answer: str,
    chunks: list[Chunk],
    llm,
) -> CriticResult:
    """Inner critic logic (called with timeout wrapper above)."""
    # Step 1: Extract claims
    claim_texts = await extract_claims(answer, llm)

    if not claim_texts:
        logger.warning("No claims extracted — returning neutral confidence")
        return CriticResult(
            claims=[],
            overall_confidence=0.7,
            needs_retry=False,
            failed_claims=[],
            legal_standing_score=50.0,
        )

    # Step 2: Score each claim
    scored_claims = score_claims(claim_texts, chunks)

    # Step 3: Identify failures
    failed_claims = [c for c in scored_claims if not c.is_grounded]

    # Step 4: Determine retry
    needs_retry = len(failed_claims) >= settings.critic_min_failures

    # Step 5: Overall confidence
    confidence = compute_overall_confidence(scored_claims)

    # Step 6: Legal standing score
    legal_standing = calculate_legal_standing_score(scored_claims, chunks)

    logger.info(
        f"Critic result: {len(failed_claims)}/{len(scored_claims)} claims failed, "
        f"confidence={confidence:.3f}, legal_standing={legal_standing:.1f}, retry={needs_retry}"
    )

    return CriticResult(
        claims=scored_claims,
        overall_confidence=confidence,
        needs_retry=needs_retry,
        failed_claims=failed_claims,
        legal_standing_score=legal_standing,
    )


async def refine_query(
    original_query: str,
    failed_claims: list[Claim],
    llm,
) -> str:
    """
    Generate a refined search query based on which claims failed grounding.
    Used to drive the retry loop with a better-targeted retrieval.
    """
    failed_text = "\n".join(f"- {c.text}" for c in failed_claims)

    try:
        response = await llm.ainvoke(
            QUERY_REFINER_PROMPT.format(
                failed_claims=failed_text,
                original_query=original_query,
            )
        )
        refined = response.content if hasattr(response, "content") else str(response)
        refined = refined.strip().strip('"').strip("'")
        logger.info(f"Refined query: {refined[:100]}")
        return refined
    except Exception as e:
        logger.warning(f"Query refinement failed: {e} — using original query")
        return original_query
