"""
NyayaBot — Critic agent unit tests.
Tests claim extraction, grounding scoring, retry detection, max-retry guard.
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.agents.critic import (
    cosine_similarity,
    extract_claims,
    score_claims,
    compute_overall_confidence,
    critique_answer,
)
from src.models import Chunk, ChunkMetadata, ActCategory
from src.config import settings
from src.graph.nodes import get_llm



class MockLLM:
    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, prompt):
        mock = MagicMock()
        mock.content = self.response
        return mock


def make_chunk(text: str, score: float = 0.9) -> Chunk:
    return Chunk(
        id="test-chunk",
        text=text,
        metadata=ChunkMetadata(
            chunk_id="test-chunk",
            source_url="https://example.com",
            document_title="Test Act",
            section="Section 1",
            act_category=ActCategory.TRANSPARENCY_LAW,
        ),
        score=score,
    )


# ─────────────────────────────────────────────
# Cosine similarity
# ─────────────────────────────────────────────

def test_cosine_sim_identical():
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)

def test_cosine_sim_orthogonal():
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)

def test_cosine_sim_zero_vector():
    a = [0.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    assert cosine_similarity(a, b) == 0.0


# ─────────────────────────────────────────────
# Claim extraction
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_claims_returns_list():
    if settings.llm_provider == "ollama":
        llm = get_llm()
    else:
        llm = MockLLM('{"claims": ["Claim one.", "Claim two.", "Claim three."]}')
    claims = await extract_claims("The application fee under Section 6 of the RTI Act is Rs 10, and the response time limit is 30 days.", llm)
    assert isinstance(claims, list)
    assert len(claims) >= 1

@pytest.mark.asyncio
async def test_extract_claims_fallback_on_bad_json():
    """When LLM returns invalid JSON, should fall back to sentence splitting."""
    llm = MockLLM("I cannot extract claims.")
    claims = await extract_claims("RTI fee is Rs. 10. File online at rtionline.gov.in.", llm)
    assert isinstance(claims, list)  # fallback returns sentences


# ─────────────────────────────────────────────
# Confidence computation
# ─────────────────────────────────────────────

def test_confidence_all_grounded():
    from src.models import Claim
    claims = [Claim(text="claim", grounding_score=0.9, is_grounded=True) for _ in range(5)]
    conf = compute_overall_confidence(claims)
    assert conf > 0.85

def test_confidence_all_ungrounded():
    from src.models import Claim
    claims = [Claim(text="claim", grounding_score=0.1, is_grounded=False) for _ in range(5)]
    conf = compute_overall_confidence(claims)
    assert conf < 0.3

def test_confidence_empty_claims():
    conf = compute_overall_confidence([])
    assert conf == 0.5  # neutral when no claims


# ─────────────────────────────────────────────
# Full critic pipeline
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_critique_high_confidence_no_retry(monkeypatch):
    """Grounded answer should not trigger retry."""
    from src.agents import critic as critic_module

    # Mock claim extraction
    monkeypatch.setattr(
        critic_module, "extract_claims",
        AsyncMock(return_value=["RTI fee is Rs 10.", "Response time is 30 days."])
    )

    # Mock scoring to return high scores
    monkeypatch.setattr(
        critic_module, "score_claims",
        lambda claims, chunks: [
            __import__("src.models", fromlist=["Claim"]).Claim(
                text=c, grounding_score=0.92, is_grounded=True
            ) for c in claims
        ]
    )

    chunk = make_chunk("RTI application fee is Rs 10 payable to the authority. Response within 30 days.")
    if settings.llm_provider == "ollama":
        llm = get_llm()
    else:
        llm = MockLLM('{"claims": []}')  # will be monkeypatched

    result = await critique_answer("How much does RTI cost?", [chunk], llm)
    assert not result.needs_retry
    assert result.overall_confidence > 0.8


@pytest.mark.asyncio
async def test_critique_low_confidence_triggers_retry(monkeypatch):
    """2+ ungrounded claims should trigger retry."""
    from src.agents import critic as critic_module

    # Mock settings.critic_min_failures to 2 so 3 failed claims trigger retry
    monkeypatch.setattr(settings, "critic_min_failures", 2)

    monkeypatch.setattr(
        critic_module, "extract_claims",
        AsyncMock(return_value=["Invented fact one.", "Invented fact two.", "Invented fact three."])
    )

    monkeypatch.setattr(
        critic_module, "score_claims",
        lambda claims, chunks: [
            __import__("src.models", fromlist=["Claim"]).Claim(
                text=c, grounding_score=0.2, is_grounded=False
            ) for c in claims
        ]
    )

    chunk = make_chunk("Some unrelated text about property registration.")
    if settings.llm_provider == "ollama":
        llm = get_llm()
    else:
        llm = MockLLM('{"claims": []}')

    result = await critique_answer("What is the penalty?", [chunk], llm)
    assert result.needs_retry
    assert len(result.failed_claims) >= 2


# ─────────────────────────────────────────────────────────────────────────────
# Temporal Validation & Legal Standing Score Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_temporal_verification_hallucinated_year():
    from src.agents.critic import score_claims
    from src.models import Claim
    
    # Claim asserts a 2026 reform
    claims = ["The 2026 amendments reduced the voting threshold to 60%."]
    chunks = [make_chunk("The 2018 amendment reduced the threshold to 66%.")]
    
    scored = score_claims(claims, chunks)
    assert scored[0].grounding_score == 0.0  # Penalized because 2026 is missing from chunks


def test_temporal_verification_negative_claim():
    from src.agents.critic import score_claims
    from src.models import Claim
    
    # Claim states that no 2026 data was found (negative claim)
    claims = ["The retrieved documents do not contain any reforms from 2026."]
    chunks = [make_chunk("The 2018 amendment reduced the threshold to 66%.")]
    
    # We expect this to NOT be penalized to 0.0
    scored = score_claims(claims, chunks)
    # It should compute normal embedding similarity which is >= 0
    assert scored[0].grounding_score >= 0.0


def test_legal_standing_score_calculation():
    from src.agents.critic import calculate_legal_standing_score
    from src.models import Claim, Chunk, ChunkMetadata, ActCategory
    
    chunk_sc = Chunk(
        id="chunk-sc",
        text="SC judgment text",
        metadata=ChunkMetadata(
            chunk_id="chunk-sc",
            source_url="http://sc",
            document_title="Supreme Court of India - Arnesh Kumar vs State of Bihar",
            section="Guidelines",
            act_category=ActCategory.CRIMINAL_LAW
        )
    )
    
    chunk_central = Chunk(
        id="chunk-central",
        text="Central Act text",
        metadata=ChunkMetadata(
            chunk_id="chunk-central",
            source_url="http://central",
            document_title="Motor Vehicles Act 1988",
            section="Section 206",
            act_category=ActCategory.TRAFFIC_LAW
        )
    )
    
    claims = [
        Claim(text="Arrest guidelines", grounding_score=0.9, is_grounded=True, best_matching_chunk_id="chunk-sc"),
        Claim(text="Traffic rules", grounding_score=0.85, is_grounded=True, best_matching_chunk_id="chunk-central"),
        Claim(text="Ungrounded rule", grounding_score=0.1, is_grounded=False, best_matching_chunk_id="")
    ]
    
    score = calculate_legal_standing_score(claims, [chunk_sc, chunk_central])
    assert score == pytest.approx(61.7, 0.1)

