"""
NyayaBot — LangGraph state definition.
"""
from __future__ import annotations

from typing import Annotated, Any, Optional
from typing_extensions import TypedDict

from src.models import Chunk, Citation, Claim, RouteType


class RAGState(TypedDict):
    """The complete state flowing through the LangGraph state machine."""

    # Input
    query: str
    session_id: str

    # Routing
    route: Optional[str]           # RETRIEVE | MEMORY | TOOL | CHITCHAT
    route_confidence: float

    # Cache
    cache_hit: bool

    # Retrieval
    hyde_query: str                # HyDE-expanded query text
    hyde_embedding: Optional[list[float]]
    retrieved_chunks: list[Chunk]

    # Generation
    context: str
    answer: str
    citations: list[Citation]

    # Critic / Self-correction
    claims: list[Claim]
    grounding_scores: list[float]
    failed_claims: list[Claim]
    retry_count: int
    confidence_score: float
    legal_standing_score: float

    # Trust fix — Draft management
    # draft_1_text: preserves the first generated answer before any retry overwrites it.
    # This lets the backend send the original draft to the frontend for version history,
    # and lets the frontend perform an atomic replacement (not a live erase).
    draft_1_text: str              # set by generate_node on first generation (retry_count==0)

    # Memory
    conversation_history: list[dict]

    # Deep Search (Iterative Legal Analysis)
    deep_search: bool
    deep_search_count: int
    deep_thought: str
    next_query: str
    satisfy: bool

    # Output metadata
    error: Optional[str]
    preferred_language: Optional[str]

