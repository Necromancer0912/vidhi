"""
NyayaBot — LangGraph graph builder.
Wires all nodes together with conditional edges and retry loop.
"""
from __future__ import annotations

import logging
from functools import partial

from langgraph.graph import END, StateGraph

from src.cache.redis_store import SemanticCache, ConversationMemory
from src.config import settings
from src.graph.nodes import (
    cache_check_node,
    cache_store_node,
    chitchat_node,
    emergency_node,
    generate_node,
    hybrid_search_node,
    hyde_node,
    memory_recall_node,
    refine_query_node,
    rerank_node,
    router_node,
    critic_node,
    tool_call_node,
    deep_search_planner_node,
    deep_search_retrieval_node,
)
from src.graph.state import RAGState
from src.retrieval.sparse import BM25Retriever

logger = logging.getLogger(__name__)


def cache_hit_router(state: RAGState) -> str:
    """After cache check: if hit → END, else → router."""
    return "END" if state.get("cache_hit") else "router"


def route_selector(state: RAGState) -> str:
    """After router: send to appropriate pipeline."""
    route = state.get("route", "RETRIEVE")
    if route == "RETRIEVE":
        return "deep_search_planner" if state.get("deep_search") else "hyde"
    return {
        "EMERGENCY": "emergency",   # Phase 3.2: fast-path, bypasses HyDE
        "MEMORY": "memory_recall",
        "TOOL": "tool_call",
        "CHITCHAT": "chitchat",
    }.get(route, "hyde")



def critic_decision(state: RAGState) -> str:
    """After critic: retry if needed and under max retries, else done.
    
    Rules (all must be true to trigger retry):
      1. Route must be RETRIEVE (EMERGENCY and others never retry)
      2. retry_count must be under max_retries
      3. Enough claims must have failed (>= critic_min_failures)
      4. Hard floor: if confidence > 0.55 AND answer > 300 chars, always pass
         (a reasonably long, mostly-grounded answer is good enough)
    """
    route = state.get("route", "RETRIEVE")
    retry_count = state.get("retry_count", 0)
    failed_claims = state.get("failed_claims", [])
    confidence = state.get("confidence_score", 0.0)
    answer = state.get("answer", "")

    # Deep Search has its own multi-step loop. We bypass standard critic retry loop.
    if state.get("deep_search"):
        return "done"

    # Rule 1: Only RETRIEVE route ever retries (EMERGENCY speed > perfection)
    if route not in ("RETRIEVE",):
        return "done"

    # Rule 4: Hard confidence floor — long, mostly-grounded answers pass unconditionally
    # This prevents retries on answers that are actually fine (≥55% confidence, ≥300 chars)
    if confidence >= 0.55 and len(answer) >= 300:
        return "done"

    # Rules 2 & 3: Retry only if under limit and enough claims failed
    needs_retry = len(failed_claims) >= settings.critic_min_failures
    if needs_retry and retry_count < settings.max_retries:
        logger.info(f"Critic triggered retry #{retry_count + 1} "
                    f"(conf={confidence:.3f}, failed={len(failed_claims)} claims)")
        return "retry"

    return "done"



def deep_search_router(state: RAGState) -> str:
    """After deep search planner: decide whether to search more or generate final answer."""
    satisfy = state.get("satisfy", False)
    count = state.get("deep_search_count", 0)

    # Hard stop at 4 loops to prevent infinite calls
    if satisfy or count >= 4:
        logger.info(f"Deep search complete. Satisfied={satisfy}, loops={count}. Routing to generate.")
        return "generate"

    logger.info(f"Deep search continuing. Loop count: {count}. Routing to deep_search_retrieval.")
    return "deep_search_retrieval"


def build_graph(
    cache: SemanticCache,
    memory_store: ConversationMemory,
    dense_retriever,
    bm25_retriever: BM25Retriever,
):
    """
    Build and compile the full NyayaBot LangGraph state machine.
    
    Graph topology (Updated for Deep Search):
    
    cache_check → [END (hit) | router]
    router → [hyde | deep_search_planner | memory_recall | tool_call | chitchat]
    hyde → hybrid_search → rerank → generate
    deep_search_planner → [deep_search_retrieval → deep_search_planner (loop) | generate]
    generate → critic → [refine_query → hybrid_search | cache_store → END]
    memory_recall → END
    tool_call → END
    chitchat → END

    Retry loop: refine_query overwrites state["query"] with the refined text
    and resets hyde_embedding, then re-enters at hybrid_search — HyDE is
    intentionally skipped on retries for latency, so dense retrieval embeds
    the refined query text directly.
    """
    graph = StateGraph(RAGState)

    # ── Add nodes ──────────────────────────────
    graph.add_node("cache_check", partial(cache_check_node, cache=cache))
    graph.add_node("router", router_node)
    graph.add_node("hyde", hyde_node)
    graph.add_node(
        "hybrid_search",
        partial(hybrid_search_node, dense_retriever=dense_retriever, bm25_retriever=bm25_retriever),
    )
    graph.add_node("rerank", rerank_node)
    graph.add_node("generate", generate_node)
    graph.add_node("critic", critic_node)
    graph.add_node("refine_query", refine_query_node)
    graph.add_node("cache_store", partial(cache_store_node, cache=cache))
    graph.add_node("memory_recall", partial(memory_recall_node, memory_store=memory_store))
    graph.add_node("tool_call", tool_call_node)
    graph.add_node("chitchat", chitchat_node)
    # Phase 3.2: Emergency fast-path node
    graph.add_node(
        "emergency",
        partial(emergency_node, dense_retriever=dense_retriever, bm25_retriever=bm25_retriever),
    )
    # Deep Search nodes
    graph.add_node("deep_search_planner", deep_search_planner_node)
    graph.add_node(
        "deep_search_retrieval",
        partial(deep_search_retrieval_node, dense_retriever=dense_retriever, bm25_retriever=bm25_retriever),
    )

    # ── Set entry point ─────────────────────────
    graph.set_entry_point("cache_check")

    # ── Edges ───────────────────────────────────

    # Cache check → router or END
    graph.add_conditional_edges(
        "cache_check",
        cache_hit_router,
        {"END": END, "router": "router"},
    )

    # Router → branch
    graph.add_conditional_edges(
        "router",
        route_selector,
        {
            "hyde": "hyde",
            "deep_search_planner": "deep_search_planner",
            "emergency": "emergency",   # Phase 3.2
            "memory_recall": "memory_recall",
            "tool_call": "tool_call",
            "chitchat": "chitchat",
        },
    )

    # Normal retrieval chain
    graph.add_edge("hyde", "hybrid_search")
    graph.add_edge("hybrid_search", "rerank")
    graph.add_edge("rerank", "generate")

    # Deep Search loop
    graph.add_conditional_edges(
        "deep_search_planner",
        deep_search_router,
        {
            "generate": "generate",
            "deep_search_retrieval": "deep_search_retrieval",
        },
    )
    graph.add_edge("deep_search_retrieval", "deep_search_planner")

    # Common generation post-processing
    graph.add_edge("generate", "critic")

    # Critic → retry or done
    graph.add_conditional_edges(
        "critic",
        critic_decision,
        {
            "retry": "refine_query",
            "done": "cache_store",
        },
    )

    # Retry loop: refine → re-search (goes back to hybrid_search, skips HyDE for speed)
    graph.add_edge("refine_query", "hybrid_search")

    # Terminal nodes
    graph.add_edge("cache_store", END)
    graph.add_edge("memory_recall", END)
    graph.add_edge("tool_call", END)
    graph.add_edge("chitchat", END)
    # Phase 3.2: Emergency → cache_store (bypasses critic entirely)
    graph.add_edge("emergency", "cache_store")

    compiled = graph.compile()
    logger.info("NyayaBot LangGraph compiled successfully")
    return compiled


def get_initial_state(query: str, session_id: str, history: list[dict] = None, deep_search: bool = False, preferred_language: Optional[str] = None) -> RAGState:
    """Create the initial state for a new query."""
    return RAGState(
        query=query,
        session_id=session_id,
        route=None,
        route_confidence=0.0,
        cache_hit=False,
        hyde_query="",
        hyde_embedding=None,
        retrieved_chunks=[],
        context="",
        answer="",
        citations=[],
        claims=[],
        grounding_scores=[],
        failed_claims=[],
        retry_count=0,
        confidence_score=0.0,
        legal_standing_score=0.0,
        draft_1_text="",       # will be set by generate_node on first pass
        conversation_history=history or [],
        error=None,
        deep_search=deep_search,
        deep_search_count=0,
        deep_thought="",
        next_query="",
        satisfy=False,
        preferred_language=preferred_language,
    )

