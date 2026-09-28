"""
NyayaBot — All Pydantic models / schemas used across the system.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# UI languages the frontend can request answers in.
SupportedLanguage = Literal["en", "hi", "bn", "pa", "gu", "mr", "ta", "te", "kn", "ml", "or"]

# Regex to match ANSI escape sequences (colors, styles, etc.)
ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def sanitise_text(text: str) -> str:
    """
    Sanitises input text by:
    1. Stripping ANSI escape sequences
    2. Stripping null bytes and other control characters (category Cc)
       except for carriage return (\r), newline (\n), and tab (\t) to preserve formatting.
    3. Trimming leading and trailing whitespace.
    """
    # 1. Remove ANSI escape sequences
    text = ANSI_ESCAPE.sub("", text)
    # 2. Filter Cc control characters, retaining valid formatting whitespace
    text = "".join(c for c in text if c in ("\n", "\r", "\t") or unicodedata.category(c) != "Cc")
    return text.strip()


# ─────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────


class RouteType(str, Enum):
    RETRIEVE = "RETRIEVE"
    EMERGENCY = "EMERGENCY"  # Phase 3.2: fast-path for on-the-spot legal help
    MEMORY = "MEMORY"
    TOOL = "TOOL"
    CHITCHAT = "CHITCHAT"


class RouteDecision(BaseModel):
    route: RouteType
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)


# ─────────────────────────────────────────────
# Document / Chunk
# ─────────────────────────────────────────────


class ActCategory(str, Enum):
    TRANSPARENCY_LAW = "transparency_law"
    CONSUMER_RIGHTS = "consumer_rights"
    LABOUR_LAW = "labour_law"
    CRIMINAL_LAW = "criminal_law"
    CIVIL_LAW = "civil_law"
    TAX_LAW = "tax_law"
    CORPORATE_LAW = "corporate_law"
    REAL_ESTATE = "real_estate"
    CONSTITUTIONAL = "constitutional"
    SOCIAL_WELFARE = "social_welfare"
    TRAFFIC_LAW = "traffic_law"  # Phase 1.1: Motor Vehicles Act + CMV Rules
    SITUATION_GUIDE = "situation_guide"  # Phase 6.1: pre-built situation templates
    GENERAL = "general"


class ChunkMetadata(BaseModel):
    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_url: str
    document_title: str
    section: str = ""
    act_category: ActCategory = ActCategory.GENERAL
    last_updated: str = ""
    language: str = "en"
    page_number: int = 0
    chunk_index: int = 0


class Chunk(BaseModel):
    id: str
    text: str
    metadata: ChunkMetadata
    score: float = 0.0  # retrieval relevance score
    embedding: Optional[list[float]] = None


# ─────────────────────────────────────────────
# Critic / Grounding
# ─────────────────────────────────────────────


class Claim(BaseModel):
    text: str
    grounding_score: float = 0.0
    is_grounded: bool = True
    best_matching_chunk_id: str = ""


class CriticResult(BaseModel):
    claims: list[Claim]
    overall_confidence: float
    needs_retry: bool
    failed_claims: list[Claim]
    legal_standing_score: float = 0.0


# ─────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────


class CachedResponse(BaseModel):
    answer: str
    citations: list[dict]
    confidence_score: float
    route: str
    timestamp: float


# ─────────────────────────────────────────────
# Conversation / Memory
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# API Request / Response
# ─────────────────────────────────────────────


class ConversationTurn(BaseModel):
    """A single turn of conversation history sent from the frontend."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=12000)

    @field_validator("content", mode="before")
    @classmethod
    def sanitise_content(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = sanitise_text(v)
            if not v:
                raise ValueError("Conversation turn content cannot be empty after sanitisation")
        return v


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        max_length=100,
        pattern=r"^[A-Za-z0-9_.:\-]+$",
    )
    deep_search: bool = False
    preferred_language: Optional[SupportedLanguage] = None
    # Frontend sends the prior turns so context survives server restarts.
    # When present, this takes priority over the server-side in-memory store.
    conversation_history: list[ConversationTurn] = Field(default=[], max_length=50)

    @field_validator("message", mode="before")
    @classmethod
    def sanitise_message(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = sanitise_text(v)
            if not v:
                raise ValueError("Message cannot be empty or contain only control characters")
        return v


class Citation(BaseModel):
    chunk_id: str
    document_title: str
    section: str
    source_url: str
    relevance_score: float


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    confidence_score: float
    legal_standing_score: float = 0.0
    route: RouteType
    retry_count: int
    cache_hit: bool
    session_id: str
    deep_search: bool = False


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    category_filter: Optional[ActCategory] = None


class RetrieveResponse(BaseModel):
    chunks: list[Chunk]
    query: str
    hyde_query: str = ""
    retrieval_time_ms: float


class FeedbackRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    message_id: str = Field(min_length=1, max_length=100)
    thumbs_up: bool
    comment: Optional[str] = Field(default=None, max_length=1000)


class HealthServices(BaseModel):
    qdrant: str
    redis: str
    llm: str
    embeddings: str


class HealthStack(BaseModel):
    llm: str
    vector_db: str
    cache: str


class HealthResponse(BaseModel):
    status: str
    services: HealthServices
    graph_ready: bool
    stack: HealthStack


# ─────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[str] = None
    api_key_id: Optional[str] = None


class User(BaseModel):
    user_id: str
    email: str
    is_active: bool = True
    tier: Literal["free", "pro"] = "free"


# ─────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────


class TestQAPair(BaseModel):
    question: str
    answer: str
    source_chunk_id: str
    category: ActCategory


class RAGASResult(BaseModel):
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    n_questions: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    system_type: Literal["baseline", "full"] = "full"
