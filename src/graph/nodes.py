"""
NyayaBot — LangGraph node functions.
Each node transforms the RAGState and returns a partial state update.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from src.agents.critic import critique_answer, refine_query
from src.agents.generator import generate_answer, generate_chitchat, translate_to_english
from src.agents.router import route_query
from src.cache.redis_store import ConversationMemory, SemanticCache
from src.config import settings
from src.graph.state import RAGState
from src.ingestion.embedder import get_embedding_model
from src.retrieval.fusion import reciprocal_rank_fusion
from src.retrieval.hyde import generate_hyde_query
from src.retrieval.reranker import get_reranker
from src.retrieval.sparse import BM25Retriever

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Shared singletons (created once per process)
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────
# LLM factory with automatic 429 fallback
# Primary:  gemini-2.0-flash  (15 RPM, 1500 req/day free)
# Fallback: gemini-1.5-flash (15 RPM, 1500 req/day FREE — separate quota!)
# When primary is rate-limited, calls silently retry on the fallback model.
# ─────────────────────────────────────────────────────────────────────────


class _FallbackLLM:
    """
    LangChain-compatible LLM wrapper with:
    - Automatic 429/quota fallback to a secondary model with 60s cooldown
    - <think>...</think> stripping for reasoning models (Qwen3.5, DeepSeek-R1)
    """

    def __init__(self, primary, fallback):
        self._primary = primary
        self._fallback = fallback
        self._fallback_until = 0.0
        self._cooldown_seconds = 60.0

    def _is_quota_error(self, e: Exception) -> bool:
        msg = str(e).lower()
        return "429" in msg or "quota" in msg or "rate limit" in msg or "resource_exhausted" in msg

    def _trigger_fallback(self):
        logger.warning(
            f"Primary LLM quota hit — switching to fallback for {self._cooldown_seconds}s"
        )
        self._fallback_until = time.time() + self._cooldown_seconds

    def _choose_model(self):
        if time.time() < self._fallback_until:
            return self._fallback
        return self._primary

    @staticmethod
    def _strip(text: str) -> str:
        """Remove <think>...</think> blocks emitted by reasoning models (Qwen3.5, DeepSeek-R1)."""
        import re

        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    async def ainvoke(self, *args, **kwargs):
        model = self._choose_model()
        try:
            result = await model.ainvoke(*args, **kwargs)
            if hasattr(result, "content"):
                result.content = self._strip(result.content)
            return result
        except Exception as e:
            if self._is_quota_error(e) and model is self._primary:
                self._trigger_fallback()
                result = await self._fallback.ainvoke(*args, **kwargs)
                if hasattr(result, "content"):
                    result.content = self._strip(result.content)
                return result
            raise

    def astream(self, *args, **kwargs):
        """Collect full response, strip thinking blocks, yield as single chunk."""

        async def _stream():
            from langchain_core.messages import AIMessageChunk

            model = self._choose_model()
            collected = []
            try:
                async for chunk in model.astream(*args, **kwargs):
                    content = chunk.content if hasattr(chunk, "content") else str(chunk)
                    collected.append(content)
            except Exception as e:
                if self._is_quota_error(e) and model is self._primary:
                    self._trigger_fallback()
                    collected = []
                    async for chunk in self._fallback.astream(*args, **kwargs):
                        content = chunk.content if hasattr(chunk, "content") else str(chunk)
                        collected.append(content)
                else:
                    raise
            full_text = self._strip("".join(collected))
            # Yield stripped text as word-sized chunks so SSE still feels live
            words = full_text.split(" ")
            for i, word in enumerate(words):
                piece = word if i == len(words) - 1 else word + " "
                yield AIMessageChunk(content=piece)

        return _stream()

    # Forward attribute access to primary (for LangChain internals like .bind, .with_config, etc.)
    def __getattr__(self, name):
        return getattr(self._primary, name)


# Process-level LLM singleton (reused across all requests)
_llm_instance = None


def get_llm():
    """
    Returns the process-level LLM instance.

    Google mode: returns a FallbackLLM wrapping:
      - Primary:  settings.llm_model          (gemini-2.0-flash)
      - Fallback: settings.llm_fallback_model  (gemini-1.5-flash)

    Groq mode:   returns ChatGroq directly (llama-3.3-70b-versatile).
                 14,400 free req/day — ideal for testing.

    Ollama mode: returns ChatOllama directly.
    """
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance

    if settings.llm_provider == "groq":
        from langchain_groq import ChatGroq

        _llm_instance = ChatGroq(
            model=settings.groq_model,
            groq_api_key=settings.groq_api_key,
            temperature=0.05,  # near-deterministic: no hallucination, still sounds natural
            max_tokens=2048,
        )
        logger.info(f"LLM ready: {settings.groq_model} via Groq (14,400 req/day free)")

    elif settings.llm_provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        primary = ChatGoogleGenerativeAI(
            model=settings.llm_model,
            google_api_key=settings.google_api_key,
            temperature=0.05,  # near-deterministic: no hallucination, still sounds natural
            max_tokens=2048,
        )
        fallback = ChatGoogleGenerativeAI(
            model=settings.llm_fallback_model,
            google_api_key=settings.google_api_key,
            temperature=0.05,
            max_tokens=2048,
        )
        logger.info(
            f"LLM ready: {settings.llm_model} (primary) -> {settings.llm_fallback_model} (fallback on 429)"
        )
        _llm_instance = _FallbackLLM(primary, fallback)

    elif settings.llm_provider == "vllm":
        from langchain_openai import ChatOpenAI

        _llm_instance = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.vllm_api_key or "not-set",
            base_url=settings.vllm_base_url,
            temperature=0.05,
            max_tokens=2048,
        )
        logger.info(
            f"LLM ready: {settings.llm_model} via OpenAI-compatible server at {settings.vllm_base_url}"
        )

    elif settings.llm_provider == "llamacpp":
        from langchain_openai import ChatOpenAI

        # Qwen3.5-4B is a thinking model — it always emits <think>...</think> blocks.
        # _FallbackLLM._strip() removes them transparently before the answer reaches the
        # RAG pipeline. temperature=0.6 is the official Qwen3 recommendation for thinking mode.
        base_llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llamacpp_api_key or "not-set",
            base_url=f"{settings.llamacpp_base_url}/v1",
            temperature=0.6,
            max_tokens=4096,  # must be large enough to contain the <think> block + answer
        )
        # No quota on a local server — use same instance for primary and fallback
        _llm_instance = _FallbackLLM(base_llm, base_llm)
        logger.info(
            f"LLM ready: {settings.llm_model} via llama.cpp at {settings.llamacpp_base_url}"
        )

    else:  # ollama
        from langchain_ollama import ChatOllama

        _llm_instance = ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_llm_base_url,
            temperature=0.05,  # near-deterministic: no hallucination, still sounds natural
            num_predict=2048,
        )

    return _llm_instance


# ─────────────────────────────────────────────
# Node: Semantic Cache Check
# ─────────────────────────────────────────────


async def cache_check_node(state: RAGState, cache: SemanticCache) -> dict:
    """Check if an identical/near-duplicate query has been answered recently."""
    if state.get("deep_search"):
        logger.info(
            f"Deep search mode enabled: bypassing semantic cache check for query: '{state['query'][:50]}'"
        )
        try:
            from src.observability.prometheus_metrics import CACHE_MISSES

            CACHE_MISSES.inc()
        except Exception as e:
            logger.warning(f"Failed to record CACHE_MISSES metric: {e}")
        return {"cache_hit": False}

    hit = cache.get(state["query"])
    if hit:
        logger.info("Cache HIT")
        try:
            from src.observability.prometheus_metrics import CACHE_HITS

            CACHE_HITS.inc()
        except Exception as e:
            logger.warning(f"Failed to record CACHE_HITS metric: {e}")
        return {
            "cache_hit": True,
            "answer": hit.get("answer", ""),
            "citations": hit.get("citations", []),
            "confidence_score": hit.get("confidence_score", 0.0),
            "legal_standing_score": hit.get("legal_standing_score", 0.0),
            "route": hit.get("route", "RETRIEVE"),
            "retry_count": 0,
        }
    try:
        from src.observability.prometheus_metrics import CACHE_MISSES

        CACHE_MISSES.inc()
    except Exception as e:
        logger.warning(f"Failed to record CACHE_MISSES metric: {e}")
    return {"cache_hit": False}


# ─────────────────────────────────────────────
# Node: Router
# ─────────────────────────────────────────────


async def router_node(state: RAGState) -> dict:
    """Classify the query into RETRIEVE | MEMORY | TOOL | CHITCHAT."""
    llm = get_llm()
    decision = await route_query(state["query"], llm)
    logger.info(f"Route: {decision.route.value} (conf={decision.confidence:.2f})")
    try:
        from src.observability.prometheus_metrics import ROUTING_DECISIONS

        ROUTING_DECISIONS.labels(route=decision.route.value).inc()
    except Exception as e:
        logger.warning(f"Failed to record ROUTING_DECISIONS metric: {e}")
    return {
        "route": decision.route.value,
        "route_confidence": decision.confidence,
    }


# ─────────────────────────────────────────────
# Node: HyDE Query Expansion
# ─────────────────────────────────────────────


async def hyde_node(state: RAGState) -> dict:
    """Generate a hypothetical document and its embedding for richer retrieval."""
    llm = get_llm()
    # On retries the refined text is already in "query" (refine_query_node
    # overwrites it) and the retry edge re-enters at hybrid_search, so this
    # node only ever sees the original query.
    query = state.get("query", "")

    # Translate query to English if non-English
    query_en = await translate_to_english(query, llm)

    hyde_text, hyde_embed = await generate_hyde_query(query_en, llm)
    return {
        "hyde_query": hyde_text,
        "hyde_embedding": hyde_embed,
    }


# ─────────────────────────────────────────────
# Node: Hybrid Search (Dense + Sparse + RRF)
# ─────────────────────────────────────────────


async def hybrid_search_node(
    state: RAGState,
    dense_retriever,
    bm25_retriever: BM25Retriever,
) -> dict:
    """Run dense + BM25 retrieval, fuse with RRF, and accumulate results on retries."""
    query = state.get("query", "")
    hyde_embed = state.get("hyde_embedding")
    retry_count = state.get("retry_count", 0)
    llm = get_llm()

    # Translate query to English if non-English
    query_en = await translate_to_english(query, llm)

    # Dense retrieval (use HyDE embedding if available)
    dense_results = await dense_retriever.retrieve(
        query=query_en,
        top_k=settings.top_k_retrieval,
        query_vector=hyde_embed,
    )

    # BM25 sparse retrieval
    sparse_results = bm25_retriever.retrieve(
        query=query_en,
        top_k=settings.top_k_retrieval,
    )

    # RRF fusion
    fused = reciprocal_rank_fusion(dense_results, sparse_results)
    logger.info(
        f"Hybrid search: {len(dense_results)} dense + {len(sparse_results)} sparse → {len(fused)} fused"
    )

    # Accumulate chunks across retries (multi-hop/sequential retrieval)
    if retry_count > 0:
        existing_chunks = state.get("retrieved_chunks", [])
        seen_ids = set()
        combined = []
        # Prioritize new search results first, then preserve existing ones
        for chunk in fused + existing_chunks:
            if chunk.id not in seen_ids:
                seen_ids.add(chunk.id)
                combined.append(chunk)
        logger.info(
            f"Retry #{retry_count}: Accumulated retrieved chunks from {len(existing_chunks)} to {len(combined)}"
        )
        return {"retrieved_chunks": combined}

    return {"retrieved_chunks": fused}


# ─────────────────────────────────────────────
# Node: Re-ranking
# ─────────────────────────────────────────────


async def rerank_node(state: RAGState) -> dict:
    """Re-rank RRF candidates with the cross-encoder (ENABLE_RERANKER=true).

    Falls back to keeping the RRF order when disabled or on any reranker
    failure, so retrieval never breaks because of the model.
    """
    chunks = state.get("retrieved_chunks", [])
    top_k = settings.top_k_rerank

    if not settings.enable_reranker or len(chunks) <= 1:
        logger.info(f"Rerank pass-through: keeping top {min(len(chunks), top_k)} chunks")
        return {"retrieved_chunks": chunks[:top_k]}

    query = state.get("query", "")
    t0 = time.perf_counter()
    try:
        reranker = get_reranker()
        reranked = await asyncio.to_thread(reranker.rerank, query, chunks, top_k)
        logger.info(
            f"Rerank: {len(chunks)}→{len(reranked)} in {(time.perf_counter() - t0) * 1000:.0f}ms"
        )
        return {"retrieved_chunks": reranked}
    except Exception as exc:
        logger.warning(f"Rerank failed ({exc}); keeping RRF order")
        return {"retrieved_chunks": chunks[:top_k]}


# ─────────────────────────────────────────────
# Node: Generate Answer
# ─────────────────────────────────────────────


async def generate_node(state: RAGState) -> dict:
    """Generate grounded answer from retrieved chunks."""
    llm = get_llm()
    query = state.get("query", "")
    chunks = state.get("retrieved_chunks", [])
    history = state.get("conversation_history", [])
    retry_count = state.get("retry_count", 0)

    answer, citations = await generate_answer(
        query,
        chunks,
        history,
        llm,
        preferred_language=state.get("preferred_language"),
    )
    logger.info(f"Generated answer ({len(answer)} chars) with {len(citations)} citations")

    result = {
        "answer": answer,
        "citations": citations,
    }

    # On first generation (before any retry), preserve the original answer.
    # draft_1_text is what the user was shown while the critic ran.
    # The backend uses this to send version history in the final_answer SSE event.
    if retry_count == 0:
        result["draft_1_text"] = answer

    return result


# ─────────────────────────────────────────────
# Node: Critic
# ─────────────────────────────────────────────


async def critic_node(state: RAGState) -> dict:
    """Decompose answer into claims, score each, decide if retry needed."""
    llm = get_llm()
    answer = state.get("answer", "")
    chunks = state.get("retrieved_chunks", [])

    critic_result = await critique_answer(answer, chunks, llm)
    try:
        from src.observability.prometheus_metrics import CONFIDENCE_HISTOGRAM

        CONFIDENCE_HISTOGRAM.observe(critic_result.overall_confidence)
    except Exception as e:
        logger.warning(f"Failed to record CONFIDENCE_HISTOGRAM metric: {e}")

    return {
        "claims": critic_result.claims,
        "grounding_scores": [c.grounding_score for c in critic_result.claims],
        "failed_claims": critic_result.failed_claims,
        "confidence_score": critic_result.overall_confidence,
        "legal_standing_score": critic_result.legal_standing_score,
    }


# ─────────────────────────────────────────────
# Node: Query Refiner (for retry)
# ─────────────────────────────────────────────


async def refine_query_node(state: RAGState) -> dict:
    """Rephrase the query based on which claims failed, for a better retry."""
    llm = get_llm()
    original_query = state.get("query", "")
    failed_claims = state.get("failed_claims", [])

    refined = await refine_query(original_query, failed_claims, llm)
    retry_count = state.get("retry_count", 0) + 1

    logger.info(f"Query refined for retry #{retry_count}: {refined[:80]}")
    try:
        from src.observability.prometheus_metrics import CRITIC_RETRIES

        route_val = state.get("route", "RETRIEVE") or "RETRIEVE"
        CRITIC_RETRIES.labels(route=route_val).inc()
    except Exception as e:
        logger.warning(f"Failed to record CRITIC_RETRIES metric: {e}")

    return {
        "query": refined,  # Replace query with refined for next iteration
        "retry_count": retry_count,
        "hyde_embedding": None,  # Reset hyde embedding so hybrid search embeds the refined query text
    }


# ─────────────────────────────────────────────
# Node: Cache Store
# ─────────────────────────────────────────────


async def cache_store_node(state: RAGState, cache: SemanticCache) -> dict:
    """Store successful responses in semantic cache."""
    if state.get("confidence_score", 0) > 0.6:  # only cache reasonably confident answers
        cache.set(
            query=state["query"],
            response={
                "answer": state.get("answer", ""),
                "citations": [
                    c.model_dump() if hasattr(c, "model_dump") else c
                    for c in state.get("citations", [])
                ],
                "confidence_score": state.get("confidence_score", 0),
                "legal_standing_score": state.get("legal_standing_score", 0.0),
                "route": state.get("route", "RETRIEVE"),
            },
        )
    return {}


# ─────────────────────────────────────────────
# Node: Memory Recall
# ─────────────────────────────────────────────


async def memory_recall_node(state: RAGState, memory_store: ConversationMemory) -> dict:
    """Retrieve relevant conversation history for memory-type queries."""
    session_id = state.get("session_id", "")
    history = memory_store.get_history(session_id)
    pref_lang = state.get("preferred_language", "en")

    # For memory queries, construct an answer from recent history
    if history:
        context = "\n".join(
            f"{'User' if t['role'] == 'user' else 'NyayaBot'}: {t['content']}"
            for t in history[-6:]  # last 3 turns
        )
        llm = get_llm()
        prompt = f"Based on this conversation history, answer the user's question.\n\nHistory:\n{context}\n\nQuestion: {state['query']}"
        if pref_lang and pref_lang.lower() != "en":
            lang_names = {
                "hi": "Hindi (Devanagari script)",
                "bn": "Bengali (Bangla script)",
                "pa": "Punjabi (Gurmukhi script)",
                "ta": "Tamil (Tamil script)",
                "te": "Telugu (Telugu script)",
                "mr": "Marathi (Devanagari script)",
                "gu": "Gujarati (Gujarati script)",
                "kn": "Kannada (Kannada script)",
                "ml": "Malayalam (Malayalam script)",
                "or": "Odia (Odia script)",
                "as": "Assamese (Assamese script)",
                "ur": "Urdu (Arabic script)",
                "en": "English",
            }
            lang_name = lang_names.get(pref_lang.lower(), pref_lang)
            prompt = (
                f"CRITICAL: The user has selected {lang_name} as their preferred language.\n"
                f"THIS PREFERENCE OVERRIDES ANY OTHER RULES. YOU MUST RESPOND ENTIRELY IN {lang_name.upper()}, USING ITS NATIVE SCRIPT. DO NOT RESPOND IN ENGLISH OR TRANSLITERATED ROMAN SCRIPT, even if the query is in English.\n\n"
                + prompt
            )
        chunks_list = []
        async for chunk in llm.astream(prompt, config={"tags": ["streamable_answer"]}):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            chunks_list.append(content)
        answer = "".join(chunks_list)
    else:
        if pref_lang == "hi":
            answer = "मेरे पास याद रखने के लिए कोई पिछली बातचीत नहीं है। क्या आप स्पष्ट कर सकते हैं कि आप किस बारे में बात कर रहे हैं?"
        elif pref_lang == "bn":
            answer = "মনে রাখার মতো আমার কাছে কোনো আগের কথোপকথন নেই। আপনি কি স্পষ্ট করতে পারেন যে আপনি কী উল্লেখ করছেন?"
        elif pref_lang == "pa":
            answer = "ਮੇਰੇ ਕੋਲ ਯਾਦ ਰੱਖਣ ਲਈ ਕੋਈ ਪਿਛਲੀ ਗੱਲਬਾਤ ਨਹੀਂ ਹੈ। ਕੀ ਤੁਸੀਂ ਸਪੱਸ਼ਟ ਕਰ ਸਕਦੇ ਹੋ ਕਿ ਤੁਸੀਂ ਕਿਸ ਬਾਰੇ ਗੱਲ ਕਰ ਰਹੇ ਹੋ?"
        else:
            answer = "I don't have any previous conversation to recall. Could you clarify what you're referring to?"

    return {
        "answer": answer,
        "citations": [],
        "confidence_score": 0.8,
    }


# ─────────────────────────────────────────────
# Node: Chitchat
# ─────────────────────────────────────────────


async def chitchat_node(state: RAGState) -> dict:
    """Handle greetings and off-topic queries."""
    llm = get_llm()
    answer = await generate_chitchat(
        state["query"],
        llm,
        preferred_language=state.get("preferred_language"),
    )
    return {
        "answer": answer,
        "citations": [],
        "confidence_score": 1.0,
        "retry_count": 0,
    }


# ─────────────────────────────────────────────
# Node: Tool Call
# ─────────────────────────────────────────────


async def tool_call_node(state: RAGState) -> dict:
    """Handle tool-type queries (court case status, etc.)."""
    query = state.get("query", "").lower()
    pref_lang = state.get("preferred_language", "en")

    # eCourts case status
    if "cnr" in query or "case status" in query:
        if pref_lang == "hi":
            answer = (
                "अपने कोर्ट केस की स्थिति की जांच करने के लिए:\n\n"
                "1. **https://ecourts.gov.in** (ई-कोर्ट सर्विसेज पोर्टल) पर जाएं\n"
                "2. 'Case Status' पर क्लिक करें\n"
                "3. अपना **CNR (केस नंबर रिकॉर्ड)** दर्ज करें — आपके केस के दस्तावेजों पर एक 16-अंकीय अनूठा नंबर\n"
                "4. वैकल्पिक रूप से कॉल करें: **1800-103-5996** (ई-कोर्ट टोल-फ्री)\n\n"
                "उच्च न्यायालय के मामलों के लिए, सीधे अपने राज्य के उच्च न्यायालय की वेबसाइट पर जाएं।"
            )
        elif pref_lang == "bn":
            answer = (
                "আপনার আদালতের মামলার স্থিতি পরীক্ষা করতে:\n\n"
                "1. **https://ecourts.gov.in** (ই-কোর্ট পরিষেবা পোর্টাল) দেখুন\n"
                "2. 'Case Status'-এ ক্লিক করুন\n"
                "3. আপনার **CNR (কেস নম্বর রেকর্ড)** লিখুন — আপনার মামলার নথিতে থাকা একটি ১৬-সংখ্যার অনন্য নম্বর\n"
                "4. বিকল্পভাবে কল করুন: **1800-103-5996** (ই-কোর্ট টোল-ফ্রি)\n\n"
                "হাইকোর্টের মামলার জন্য, সরাসরি আপনার রাজ্যের হাইকোর্টের ওয়েবসাইট দেখুন।"
            )
        elif pref_lang == "pa":
            answer = (
                "ਆਪਣੇ ਅਦਾਲਤੀ ਕੇਸ ਦੀ ਸਥਿਤੀ ਦੀ ਜਾਂਚ ਕਰਨ ਲਈ:\n\n"
                "1. **https://ecourts.gov.in** (ਈ-ਕੋਰਟਸ ਸਰਵਿਸਿਜ਼ ਪੋਰਟਲ) 'ਤੇ ਜਾਓ\n"
                "2. 'Case Status' 'ਤੇ ਕਲਿੱਕ ਕਰੋ\n"
                "3. ਆਪਣਾ **CNR (ਕੇਸ ਨੰਬਰ ਰਿਕਾਰਡ)** ਦਰਜ ਕਰੋ — ਤੁਹਾਡੇ ਕੇਸ ਦੇ ਦਸਤਾਵੇਜ਼ਾਂ 'ਤੇ 16-ਅੰਕਾਂ ਦਾ ਵਿਲੱਖਣ ਨੰਬਰ\n"
                "4. ਵਿਕਲਪਿਕ ਤੌਰ 'ਤੇ ਕਾਲ ਕਰੋ: **1800-103-5996** (ਈ-ਕੋਰਟਸ ਟੋਲ-ਫ੍ਰੀ)\n\n"
                "ਹਾਈ ਕੋਰਟ ਦੇ ਕੇਸਾਂ ਲਈ, ਸਿੱਧੇ ਆਪਣੇ ਰਾਜ ਦੀ ਹਾਈ ਕੋਰਟ ਦੀ ਵੈੱਬਸਾਈਟ 'ਤੇ ਜਾਓ।"
            )
        else:
            answer = (
                "To check your court case status:\n\n"
                "1. Visit **https://ecourts.gov.in** (eCourts Services portal)\n"
                "2. Click 'Case Status'\n"
                "3. Enter your **CNR (Case Number Record)** — a 16-digit unique number on your case papers\n"
                "4. Alternatively call: **1800-103-5996** (eCourts toll-free)\n\n"
                "For High Court cases, visit your state High Court website directly."
            )
    else:
        llm = get_llm()
        prompt = (
            f"The user is asking about a real-time query that may need external tools: {state['query']}\n"
            "Give a helpful response about where they can find this information online."
        )
        if pref_lang and pref_lang.lower() != "en":
            lang_names = {
                "hi": "Hindi (Devanagari script)",
                "bn": "Bengali (Bangla script)",
                "pa": "Punjabi (Gurmukhi script)",
                "ta": "Tamil (Tamil script)",
                "te": "Telugu (Telugu script)",
                "mr": "Marathi (Devanagari script)",
                "gu": "Gujarati (Gujarati script)",
                "kn": "Kannada (Kannada script)",
                "ml": "Malayalam (Malayalam script)",
                "or": "Odia (Odia script)",
                "as": "Assamese (Assamese script)",
                "ur": "Urdu (Arabic script)",
                "en": "English",
            }
            lang_name = lang_names.get(pref_lang.lower(), pref_lang)
            prompt = (
                f"CRITICAL: The user has selected {lang_name} as their preferred language.\n"
                f"THIS PREFERENCE OVERRIDES ANY OTHER RULES. YOU MUST RESPOND ENTIRELY IN {lang_name.upper()}, USING ITS NATIVE SCRIPT. DO NOT RESPOND IN ENGLISH OR TRANSLITERATED ROMAN SCRIPT, even if the query is in English.\n\n"
                + prompt
            )
        chunks_list = []
        async for chunk in llm.astream(
            prompt,
            config={"tags": ["streamable_answer"]},
        ):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            chunks_list.append(content)
        answer = "".join(chunks_list)

    return {
        "answer": answer,
        "citations": [],
        "confidence_score": 0.9,
        "retry_count": 0,
    }


# ─────────────────────────────────────────────
# Node: Emergency (Phase 3.2)
# Fast-path for on-the-spot legal situations.
# Bypasses HyDE (saves ~3s), uses wide top_k=30
# retrieval, uses short bullet-point prompt,
# critic retry is DISABLED (speed > perfection).
# ─────────────────────────────────────────────


async def emergency_node(
    state: RAGState,
    dense_retriever,
    bm25_retriever: BM25Retriever,
) -> dict:
    """
    Emergency fast-path:
      1. Run hybrid search with top_k=30 (wide net — capture any relevant law)
      2. Generate using EMERGENCY_SYSTEM_PROMPT (short, bullet-points, <250 words)
      3. No critic retry — speed takes priority over perfection in emergencies
      4. Confidence score still computed for display but never triggers retry
    """
    llm = get_llm()
    query = state.get("query", "")
    history = state.get("conversation_history", [])
    embedder = get_embedding_model()

    # Translate query to English if non-English
    query_en = await translate_to_english(query, llm)

    # Step 1: Direct embedding (no HyDE — saves 3–5s)
    try:
        query_vector = embedder.embed(query_en)
    except Exception as e:
        logger.warning(f"Emergency embed failed: {e} — using text-only BM25 fallback")
        query_vector = None

    # Step 2: Wide hybrid search — top_k=30 to cast the widest legal net
    emergency_top_k = 30
    try:
        dense_results = await dense_retriever.retrieve(
            query=query_en,
            top_k=emergency_top_k,
            query_vector=query_vector,
        )
    except Exception as e:
        logger.warning(f"Emergency dense retrieval failed: {e}")
        dense_results = []

    try:
        sparse_results = bm25_retriever.retrieve(query=query_en, top_k=emergency_top_k)
    except Exception as e:
        logger.warning(f"Emergency sparse retrieval failed: {e}")
        sparse_results = []

    fused = reciprocal_rank_fusion(dense_results, sparse_results)
    # Keep top 10 for the LLM context (more than normal 5, less than all 30)
    top_chunks = fused[:10]
    logger.info(
        f"Emergency search: {len(dense_results)} dense + {len(sparse_results)} sparse "
        f"→ {len(fused)} fused → top {len(top_chunks)} to LLM"
    )

    answer, citations = await generate_answer(
        query=query,
        chunks=top_chunks,
        history=history,
        llm=llm,
        emergency=True,  # uses EMERGENCY_SYSTEM_PROMPT
        preferred_language=state.get("preferred_language"),
    )

    logger.info(f"Emergency answer generated ({len(answer)} chars), {len(citations)} citations")

    # Compute a basic legal standing score for the emergency path using retrieved chunks
    standing_score = 50.0
    if top_chunks:
        try:
            from src.agents.critic import Claim, calculate_legal_standing_score

            # Mock 3 grounded claims to run the weighted calculation over top chunks
            mock_claims = [
                Claim(
                    text="Emergency right citation",
                    is_grounded=True,
                    best_matching_chunk_id=top_chunks[0].id,
                )
            ]
            if len(top_chunks) > 1:
                mock_claims.append(
                    Claim(
                        text="Emergency obligation citation",
                        is_grounded=True,
                        best_matching_chunk_id=top_chunks[1].id,
                    )
                )
            standing_score = calculate_legal_standing_score(mock_claims, top_chunks)
        except Exception as e:
            logger.warning(f"Failed to calculate emergency standing score: {e}")
            standing_score = 75.0

    return {
        "answer": answer,
        "citations": citations,
        "retrieved_chunks": top_chunks,
        "route": "EMERGENCY",
        # Confidence is set to a fixed 0.75 for emergency — no critic runs
        # so we can't compute real grounding score, but we want to show a badge
        "confidence_score": 0.75,
        "legal_standing_score": standing_score,
        "retry_count": 0,
        "draft_1_text": answer,
    }


# ─────────────────────────────────────────────
# Deep Search (Iterative Legal Analysis)
# ─────────────────────────────────────────────

DEEP_SEARCH_PLANNER_PROMPT = """You are the Deep Search Planner for NyayaBot, an advanced Indian legal assistant.
Your job is to perform deep, multi-step, and optimized legal research to provide a concrete, highly accurate legal answer.

A lawyer or citizen has asked a legal question: "{query}"

We have already performed {deep_search_count} search steps and retrieved the following legal documents:
---
{retrieved_context}
---

Your task:
1. **Analyze** the user's question, conversation history (if any), and the retrieved documents.
2. **Evaluate** if the retrieved documents are SUFFICIENT to answer the user's question with absolute legal precision (including specific section numbers, clauses, or penalties, without making assumptions).
   - *Optimization Rule:* You must minimize unnecessary searches. If you have enough information to answer the core legal question, or if searching more will not add meaningful value, you should stop. Do not search more than 5 times.
3. **Decide**:
   - If they are SUFFICIENT: Set "satisfy" to true, and explain your reasoning in "deep_thought".
   - If they are NOT SUFFICIENT (e.g. they reference another act or section not yet retrieved, or lack crucial details): Set "satisfy" to false, explain what is missing and why you need it in "deep_thought", and formulate the next highly optimized "next_query" to fetch the missing details from the database.

Return ONLY a JSON object in this exact format:
{{
  "satisfy": true,
  "deep_thought": "Your internal legal reasoning/thought process analyzing the current findings and deciding the next step.",
  "next_query": ""
}}
or:
{{
  "satisfy": false,
  "deep_thought": "Your internal legal reasoning/thought process explaining what is missing and why you need it.",
  "next_query": "The optimized search query for the next RAG step (specific keywords, act names, section numbers)"
}}
"""


async def deep_search_planner_node(state: RAGState) -> dict:
    """Plan the next retrieval query or decide if we have sufficient context to answer."""
    import json
    import re

    llm = get_llm()
    query = state.get("query", "")
    deep_search_count = state.get("deep_search_count", 0)
    retrieved_chunks = state.get("retrieved_chunks", [])

    # Format current retrieved chunks as context
    if retrieved_chunks:
        context_parts = []
        for i, chunk in enumerate(retrieved_chunks):
            source_label = chunk.metadata.document_title
            if chunk.metadata.section:
                source_label += f", {chunk.metadata.section}"
            context_parts.append(f"[SOURCE {i + 1}] {source_label}\n{chunk.text}")
        retrieved_context = "\n\n---\n\n".join(context_parts)
    else:
        retrieved_context = "No documents retrieved yet."

    prompt = DEEP_SEARCH_PLANNER_PROMPT.format(
        query=query, deep_search_count=deep_search_count, retrieved_context=retrieved_context
    )

    try:
        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        # Extract JSON
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            satisfy = bool(data.get("satisfy", False))
            deep_thought = data.get("deep_thought", "Analyzing legal sources...")
            next_query = data.get("next_query", "")

            logger.info(
                f"Deep Search Planner [Step {deep_search_count}]: satisfy={satisfy}, "
                f"thought='{deep_thought[:80]}...', next_query='{next_query}'"
            )
            return {
                "satisfy": satisfy,
                "deep_thought": deep_thought,
                "next_query": next_query,
            }
    except Exception as e:
        logger.warning(
            f"Deep search planner failed: {e} — satisfying immediately to prevent loop block"
        )

    # Fallback to satisfy to avoid infinite loop
    return {
        "satisfy": True,
        "deep_thought": "Failed to parse planning step. Proceeding with current results.",
        "next_query": "",
    }


async def deep_search_retrieval_node(
    state: RAGState,
    dense_retriever,
    bm25_retriever: BM25Retriever,
) -> dict:
    """Perform hybrid retrieval for the next query in the deep search loop, merging results."""
    next_query = state.get("next_query") or state.get("query", "")
    deep_search_count = state.get("deep_search_count", 0) + 1
    llm = get_llm()

    # Translate next_query to English
    next_query_en = await translate_to_english(next_query, llm)

    # Direct embedding for speed in deep search (saves ~3-5s per loop compared to HyDE)
    embedder = get_embedding_model()
    try:
        query_vector = embedder.embed(next_query_en)
    except Exception as e:
        logger.warning(f"Deep search embed failed for query '{next_query_en}': {e}")
        query_vector = None

    dense_results = await dense_retriever.retrieve(
        query=next_query_en,
        top_k=settings.top_k_retrieval,
        query_vector=query_vector,
    )

    sparse_results = bm25_retriever.retrieve(
        query=next_query_en,
        top_k=settings.top_k_retrieval,
    )

    fused = reciprocal_rank_fusion(dense_results, sparse_results)

    existing_chunks = state.get("retrieved_chunks", [])
    seen_ids = set()
    combined = []
    # Prioritize new search results first, then preserve existing ones
    for chunk in fused + existing_chunks:
        if chunk.id not in seen_ids:
            seen_ids.add(chunk.id)
            combined.append(chunk)

    logger.info(
        f"Deep Search Loop #{deep_search_count}: "
        f"Retrieved {len(fused)} new chunks, total accumulated: {len(combined)} chunks."
    )

    return {
        "retrieved_chunks": combined,
        "deep_search_count": deep_search_count,
    }
