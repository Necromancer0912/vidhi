"""
NyayaBot — Chat endpoint with SSE streaming.
POST /api/v1/chat — primary query endpoint.

SSE Event Protocol
──────────────────
queued       → request is waiting for a free slot
route        → routing decision (RETRIEVE / CHITCHAT / etc.)
cache_hit    → cache hit, full answer coming in 'done'
verifying    → critic is now checking answer grounding (Draft 1 is frozen, stay visible)
retry        → critic rejected Draft 1; Draft 2 is generating silently on the server.
               Frontend: keep Draft 1 visible, show amber "Improving…" banner.
               NO more token events will fire until Draft 2 is fully approved.
final_answer → Draft 2 is critic-approved and complete. Replace Draft 1 atomically.
               Carries: answer, replaced_draft (Draft 1 text), citations, confidence.
token        → streamed answer token (only for Draft 1 and cache-miss non-retry paths)
writing      → non-English only: the (unshown) English draft has started
translating  → non-English only: the finished answer is being translated
done         → final metadata (citations, confidence, latency). Always the last event.
error        → error message
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.api.main import app_state
from src.api.security import (
    client_ip,
    enforce_edge_limit,
    enforce_limit,
    optional_user,
    require_admin,
    require_user,
)
from src.cache.redis_store import redis_client
from src.config import settings
from src.cache.redis_store import Analytics
from src.graph.builder import get_initial_state
from src.models import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Concurrency control ────────────────────────────────────────────────────────────────────
_MAX_CONCURRENT = 15
_graph_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
_queue_depth: int = 0

_analytics = Analytics()


def _track_query(state: dict, message: str) -> None:
    """Record the query in analytics; failures must never affect the response."""
    try:
        _analytics.track_query(
            route=state.get("route") or "RETRIEVE",
            topic=message[:50],
            retry_count=state.get("retry_count", 0) or 0,
        )
    except Exception as exc:
        logger.debug(f"Analytics tracking failed: {exc}")


async def stream_query(request: ChatRequest, memory_key: str) -> AsyncIterator[dict]:
    """
    Stream the multi-agent RAG response via SSE.

    Trust-safe streaming protocol:
    - Draft 1 streams normally via 'token' events (user reads it)
    - When critic starts: 'verifying' event fires (frontend shows verifying badge)
    - If critic PASSES: 'done' event fires immediately (Draft 1 becomes final)
    - If critic FAILS:  'retry' event fires (frontend shows amber banner, keeps Draft 1 visible)
                        Draft 2 tokens are buffered SILENTLY on the server
                        When Draft 2 is critic-approved: 'final_answer' fires with full text
                        Frontend atomically replaces Draft 1 with Draft 2 (crossfade)
    """
    global _queue_depth
    start_time = time.time()
    memory_store = app_state.memory_store

    # ── Queue notification + keepalive while waiting ──────────────────────────
    if _graph_semaphore.locked():
        _queue_depth += 1
        yield {
            "event": "queued",
            "data": json.dumps(
                {
                    "position": _queue_depth,
                    "message": "Your query is queued — please wait a moment.",
                }
            ),
        }
        while _graph_semaphore.locked():
            await asyncio.sleep(15)
            if not _graph_semaphore.locked():
                break
            yield {"event": "ping", "data": json.dumps({"alive": True})}

    async with _graph_semaphore:
        _queue_depth = max(0, _queue_depth - 1)

        # Prefer the history the frontend explicitly sent (authoritative source).
        # Fall back to in-memory store only when the client sends nothing.
        # Defensively slice to the last 50 turns regardless of source to guard
        # against oversized payloads that bypass the Pydantic max_length=50 guard
        # (e.g. server-recalled histories that predate the cap).
        if request.conversation_history:
            history = [
                {"role": t.role, "content": t.content} for t in request.conversation_history
            ][-50:]
            logger.debug(f"Using client-supplied history: {len(history)} turns")
        else:
            history = memory_store.get_history(memory_key)[-50:]
            logger.debug(f"Using server memory history: {len(history)} turns")

        preferred_lang = request.preferred_language
        if preferred_lang and preferred_lang.lower() != "en":
            from src.retrieval.translation_service import TranslationService
            translator = TranslationService.get_instance()
            query_en = await translator.translate_to_english(request.message, preferred_lang)
            history_en = []
            for turn in history:
                content_en = await translator.translate_to_english(turn["content"], preferred_lang)
                history_en.append({"role": turn["role"], "content": content_en})
            logger.debug(f"Translated query to English: '{request.message}' -> '{query_en}'")
        else:
            query_en = request.message
            history_en = history

        initial_state = get_initial_state(
            query=query_en,
            session_id=memory_key,
            history=history_en,
            deep_search=request.deep_search,
            preferred_language=None,
        )

        try:
            current_state = dict(initial_state)
            done_sent = False

            # ── Streaming state machine ───────────────────────────────────────
            # is_buffering: True when we're silently collecting Draft 2 tokens.
            # While buffering, 'token' events are NOT forwarded to the frontend.
            is_buffering = False
            writing_announced = False
            retry_buffer = []  # collects Draft 2 tokens when buffering
            draft_1_text_snapshot = ""  # captured when retry fires

            async for event in app_state.graph.astream_events(initial_state, version="v1"):
                kind = event["event"]
                name = event["name"]

                # ── Route decision ─────────────────────────────────────────────
                if kind == "on_chain_end" and "router_node" in name:
                    step_state = event["data"].get("output", {})
                    if isinstance(step_state, dict) and step_state.get("route"):
                        yield {
                            "event": "route",
                            "data": json.dumps({"route": step_state["route"]}),
                        }

                # ── Deep Search planner steps ─────────────────────────────────
                if kind == "on_chain_end" and "deep_search_planner_node" in name:
                    step_state = event["data"].get("output", {})
                    if isinstance(step_state, dict):
                        yield {
                            "event": "deep_search_step",
                            "data": json.dumps(
                                {
                                    "thought": step_state.get("deep_thought", ""),
                                    "next_query": step_state.get("next_query", ""),
                                    "satisfy": step_state.get("satisfy", False),
                                    "step": current_state.get("deep_search_count", 0),
                                }
                            ),
                        }

                # ── Critic starts checking → send verifying signal ─────────────
                # Frontend: freeze Draft 1 streaming, show "⟳ Verifying..." badge
                if kind == "on_chain_start" and "critic_node" in name:
                    yield {
                        "event": "verifying",
                        "data": json.dumps({"checking": True}),
                    }

                # ── Cache hit ─────────────────────────────────────────────────
                if kind == "on_chain_end" and "cache_check_node" in name:
                    step_state = event["data"].get("output", {})
                    if isinstance(step_state, dict) and step_state.get("cache_hit"):
                        yield {
                            "event": "cache_hit",
                            "data": json.dumps({"cached": True}),
                        }
                        cached_answer = step_state.get("answer", "")
                        if preferred_lang and preferred_lang.lower() != "en":
                            from src.retrieval.translation_service import TranslationService
                            translated_cached_answer = await TranslationService.get_instance().translate_from_english(
                                cached_answer, preferred_lang
                            )
                        else:
                            translated_cached_answer = cached_answer

                        cached_citations = [
                            c.model_dump() if hasattr(c, "model_dump") else c
                            for c in step_state.get("citations", [])
                        ]
                        memory_store.add_turn(memory_key, "user", request.message)
                        memory_store.add_turn(memory_key, "assistant", translated_cached_answer)
                        elapsed_ms = (time.time() - start_time) * 1000
                        yield {
                            "event": "done",
                            "data": json.dumps(
                                {
                                    "answer": translated_cached_answer,
                                    "citations": cached_citations,
                                    "confidence_score": step_state.get("confidence_score", 0.0),
                                    "legal_standing_score": step_state.get(
                                        "legal_standing_score", 0.0
                                    ),
                                    "retry_count": 0,
                                    "route": step_state.get("route", "RETRIEVE"),
                                    "cache_hit": True,
                                    "session_id": request.session_id,
                                    "latency_ms": round(elapsed_ms, 1),
                                }
                            ),
                        }
                        done_sent = True
                        _track_query(step_state, request.message)

                # ── Critic retry decision — switch to buffering mode ───────────
                # When refine_query_node fires it means critic rejected Draft 1.
                # We capture Draft 1's text and stop forwarding tokens to frontend.
                if kind == "on_chain_end" and "refine_query_node" in name:
                    step_state = event["data"].get("output", {})
                    if isinstance(step_state, dict):
                        retry_count = step_state.get("retry_count", 1)
                        # Snapshot Draft 1 from current_state (before it gets overwritten)
                        draft_1_text_snapshot = current_state.get(
                            "draft_1_text", ""
                        ) or current_state.get("answer", "")
                        # Enter buffering mode — Draft 2 tokens will be silent
                        is_buffering = True
                        retry_buffer = []
                        yield {
                            "event": "retry",
                            "data": json.dumps({"retry_count": retry_count}),
                        }

                # ── Track full state ──────────────────────────────────────────
                if kind == "on_chain_end":
                    output = event["data"].get("output")
                    if isinstance(output, dict):
                        current_state.update(output)

                # ── Stream LLM tokens ─────────────────────────────────────────
                if kind == "on_chat_model_stream" and "streamable_answer" in event.get("tags", []):
                    chunk = event["data"]["chunk"]
                    content = chunk.content if hasattr(chunk, "content") else str(chunk)
                    if content:
                        if is_buffering:
                            # Silently collect Draft 2 tokens — do NOT send to frontend
                            retry_buffer.append(content)
                        elif preferred_lang and preferred_lang.lower() != "en":
                            # The English draft isn't shown; tell the reader once
                            # that writing has started so the screen isn't idle.
                            if not writing_announced:
                                writing_announced = True
                                yield {"event": "writing", "data": json.dumps({"writing": True})}
                        else:
                            # Normal streaming — Draft 1 tokens go directly to the user
                            yield {
                                "event": "token",
                                "data": json.dumps({"token": content}),
                            }

                # ── Critic approves Draft 2 (cache_store fires after critic passes) ──
                # At this point retry_buffer has all of Draft 2's text.
                # Send it atomically as a 'final_answer' event.
                if kind == "on_chain_start" and "cache_store_node" in name and is_buffering:
                    # Draft 2 is critic-approved — send atomic replacement
                    draft_2_text = "".join(retry_buffer)
                    elapsed_ms = (time.time() - start_time) * 1000
                    citations = [
                        c.model_dump() if hasattr(c, "model_dump") else c
                        for c in current_state.get("citations", [])
                    ]
                    
                    if preferred_lang and preferred_lang.lower() != "en":
                        from src.retrieval.translation_service import TranslationService
                        yield {"event": "translating", "data": json.dumps({"language": preferred_lang})}
                        translated_draft_2 = await TranslationService.get_instance().translate_from_english(
                            draft_2_text, preferred_lang
                        )
                        translated_draft_1 = await TranslationService.get_instance().translate_from_english(
                            draft_1_text_snapshot, preferred_lang
                        )
                    else:
                        translated_draft_2 = draft_2_text
                        translated_draft_1 = draft_1_text_snapshot

                    yield {
                        "event": "final_answer",
                        "data": json.dumps(
                            {
                                "answer": translated_draft_2,
                                "replaced_draft": translated_draft_1,  # Draft 1 for version history
                                "citations": citations,
                                "confidence_score": current_state.get("confidence_score", 0.0),
                                "legal_standing_score": current_state.get(
                                    "legal_standing_score", 0.0
                                ),
                                "retry_count": current_state.get("retry_count", 1),
                                "latency_ms": round(elapsed_ms, 1),
                            }
                        ),
                    }
                    # Update current_state answer with english draft 2 for the done step
                    current_state["answer"] = draft_2_text
                    is_buffering = False
                    done_sent = False  # still need to send 'done' for metadata

            # ── Final done event ──────────────────────────────────────────────
            if not done_sent:
                answer = current_state.get("answer", "")
                citations = [
                    c.model_dump() if hasattr(c, "model_dump") else c
                    for c in current_state.get("citations", [])
                ]
                confidence = current_state.get("confidence_score", 0.0)
                retry_count = current_state.get("retry_count", 0)
                route = current_state.get("route", "RETRIEVE")
                cache_hit = current_state.get("cache_hit", False)

                if preferred_lang and preferred_lang.lower() != "en":
                    from src.retrieval.translation_service import TranslationService
                    yield {"event": "translating", "data": json.dumps({"language": preferred_lang})}
                    translated_answer = await TranslationService.get_instance().translate_from_english(
                        answer, preferred_lang
                    )
                else:
                    translated_answer = answer

                memory_store.add_turn(memory_key, "user", request.message)
                memory_store.add_turn(memory_key, "assistant", translated_answer)

                elapsed_ms = (time.time() - start_time) * 1000
                yield {
                    "event": "done",
                    "data": json.dumps(
                        {
                            "answer": translated_answer,
                            "citations": citations,
                            "confidence_score": confidence,
                            "legal_standing_score": current_state.get("legal_standing_score", 0.0),
                            "retry_count": retry_count,
                            "route": route,
                            "cache_hit": cache_hit,
                            "session_id": request.session_id,
                            "latency_ms": round(elapsed_ms, 1),
                            "deep_search": current_state.get("deep_search", False),
                        }
                    ),
                }
                _track_query(current_state, request.message)

        except Exception as e:
            logger.error(f"Graph execution error: {e}", exc_info=True)
            is_rate_limit = "429" in str(e) or "quota" in str(e).lower()
            error_msg = (
                "The language model is busy right now. Wait about 30 seconds and ask again."
                if is_rate_limit
                else "Something went wrong while preparing this answer. Please ask again."
            )
            yield {
                "event": "error",
                "data": json.dumps({"error": error_msg}),
            }


def memory_scope(request: Request, body: ChatRequest, user: Optional[dict]) -> str:
    """Server-side conversation memory key for this caller's session.

    The browser picks the session id, so on its own it can't identify whose
    conversation it is: anyone who guessed another visitor's id could pull
    that conversation into their own answer. The key binds it to the caller
    (account email, or IP for guests) and is hashed so no email lands in Redis.
    """
    owner = user["sub"].lower() if user else f"guest:{client_ip(request)}"
    return hashlib.sha256(f"{owner}|{body.session_id}".encode()).hexdigest()[:40]


def check_chat_access(request: Request, body: ChatRequest, user: Optional[dict]) -> None:
    """Per-minute limits for everyone; daily and global ceilings for guests.

    Accounts: 60 requests/min per email. Guests: 20/min per IP, a daily cap
    per IP, a shared per-minute ceiling across all guests, and a ceiling per
    connecting address that forged X-Forwarded-For headers can't dodge.
    Deep Search is account-only.
    """
    if user:
        enforce_limit("", user["sub"].lower(), limit=60)
        return

    ip = client_ip(request)
    enforce_limit("", ip, limit=20)
    if body.deep_search:
        raise HTTPException(status_code=403, detail="Deep Search needs a free account. Sign in to use it.")
    enforce_limit(
        "guest-day", ip, limit=settings.guest_daily_limit, window=24 * 3600,
        message="You've used today's guest answers. Create a free account to keep going.",
    )
    enforce_limit(
        "guest-all", "global", limit=settings.guest_global_rpm,
        message="Vidhi is busy with guest questions right now. Try again in a minute, or sign in.",
    )
    enforce_edge_limit(request)


@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest, http_request: Request, user: Optional[dict] = Depends(optional_user)
):
    """
    Main chat endpoint — returns SSE stream.

    Events: queued | route | cache_hit | verifying | retry | token | final_answer | done | error
    """
    check_chat_access(http_request, request, user)
    return EventSourceResponse(stream_query(request, memory_scope(http_request, request, user)))


@router.post("/chat/sync", response_model=ChatResponse)
async def chat_sync_endpoint(
    request: ChatRequest, http_request: Request, user: Optional[dict] = Depends(optional_user)
):
    """
    Synchronous chat endpoint — waits for full answer before returning.
    Useful for testing and non-streaming clients.
    """
    check_chat_access(http_request, request, user)
    memory_key = memory_scope(http_request, request, user)
    graph = app_state.graph
    memory_store = app_state.memory_store
    if request.conversation_history:
        history = [{"role": t.role, "content": t.content} for t in request.conversation_history]
    else:
        history = memory_store.get_history(memory_key)

    preferred_lang = request.preferred_language
    if preferred_lang and preferred_lang.lower() != "en":
        from src.retrieval.translation_service import TranslationService
        translator = TranslationService.get_instance()
        query_en = await translator.translate_to_english(request.message, preferred_lang)
        history_en = []
        for turn in history:
            content_en = await translator.translate_to_english(turn["content"], preferred_lang)
            history_en.append({"role": turn["role"], "content": content_en})
        logger.debug(f"Sync: Translated query to English: '{request.message}' -> '{query_en}'")
    else:
        query_en = request.message
        history_en = history

    initial_state = get_initial_state(
        query=query_en,
        session_id=memory_key,
        history=history_en,
        deep_search=request.deep_search,
        preferred_language=None,
    )

    final_state = await graph.ainvoke(initial_state)

    answer = final_state.get("answer", "")
    if preferred_lang and preferred_lang.lower() != "en":
        from src.retrieval.translation_service import TranslationService
        translated_answer = await TranslationService.get_instance().translate_from_english(
            answer, preferred_lang
        )
    else:
        translated_answer = answer

    memory_store.add_turn(memory_key, "user", request.message)
    memory_store.add_turn(memory_key, "assistant", translated_answer)
    _track_query(final_state, request.message)

    return ChatResponse(
        answer=translated_answer,
        citations=final_state.get("citations", []),
        confidence_score=final_state.get("confidence_score", 0.0),
        legal_standing_score=final_state.get("legal_standing_score", 0.0),
        route=final_state.get("route", "RETRIEVE"),
        retry_count=final_state.get("retry_count", 0),
        cache_hit=final_state.get("cache_hit", False),
        session_id=request.session_id,
        deep_search=final_state.get("deep_search", False),
    )


# ── Chat History Endpoints (Redis persistent store) ─────────────────────────────

_MAX_SESSIONS = 50
_MAX_MESSAGES = 50
_MAX_HISTORY_BYTES = 1_500_000


class HistorySaveRequest(BaseModel):
    sessions: List[Dict[str, Any]] = Field(default=[], max_length=200)
    active_chat: Optional[Dict[str, Any]] = None


class UserHistory(BaseModel):
    sessions: List[Dict[str, Any]] = []
    active_chat: Optional[Dict[str, Any]] = None


def get_current_user_email(user: dict = Depends(require_user)) -> str:
    # Saves are debounced client-side; 60 a minute is far above normal use.
    enforce_limit("history", user["sub"].lower(), limit=60)
    return user["sub"]


def _account_exists(r, email: str) -> bool:
    # Tokens are stateless, so one issued before an account was deleted still
    # verifies. Refuse it here so it can't recreate stored history.
    return r.get(f"nyaya:users:{email.lower()}") is not None


@router.get("/chat/history", response_model=UserHistory)
def get_user_history(email: str = Depends(get_current_user_email)):
    r = redis_client()
    if not r:
        return UserHistory(sessions=[], active_chat=None)
    key = f"nyaya:history:{email.lower()}"
    raw = r.get(key)
    if not raw:
        return UserHistory(sessions=[], active_chat=None)
    try:
        data = json.loads(raw)
        return UserHistory(sessions=data.get("sessions", []), active_chat=data.get("active_chat"))
    except Exception:
        return UserHistory(sessions=[], active_chat=None)


@router.post("/chat/history")
def save_user_history(request: HistorySaveRequest, email: str = Depends(get_current_user_email)):
    r = redis_client()
    if not r:
        return {"success": False, "error": "Redis unavailable"}

    # Sort sessions by ID descending (timestamp) to process newest first
    sorted_sessions = sorted(
        (x for x in request.sessions if isinstance(x.get("messages", []), list)),
        key=lambda x: x.get("id", 0) if isinstance(x.get("id"), (int, float)) else 0,
        reverse=True,
    )

    # Prune to the latest 50 sessions and limit each session's messages to the latest 50
    pruned_sessions = []
    for sess in sorted_sessions[:_MAX_SESSIONS]:
        messages = sess.get("messages", [])
        if len(messages) > _MAX_MESSAGES:
            sess["messages"] = messages[-_MAX_MESSAGES:]
        pruned_sessions.append(sess)

    # Prune active chat messages to latest 50
    active_chat = request.active_chat
    if active_chat:
        active_msgs = active_chat.get("messages", [])
        if len(active_msgs) > _MAX_MESSAGES:
            active_chat["messages"] = active_msgs[-_MAX_MESSAGES:]

    if not _account_exists(r, email):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    key = f"nyaya:history:{email.lower()}"
    data = {"sessions": pruned_sessions, "active_chat": active_chat}
    encoded = json.dumps(data)
    if len(encoded) > _MAX_HISTORY_BYTES:
        raise HTTPException(status_code=413, detail="Chat history is too large to save")
    r.set(key, encoded, ex=90 * 24 * 3600)
    return {"success": True}


@router.delete("/chat/history")
def delete_user_history(email: str = Depends(get_current_user_email)):
    r = redis_client()
    if not r:
        return {"success": False, "error": "Redis unavailable"}
    key = f"nyaya:history:{email.lower()}"
    r.delete(key)
    return {"success": True}


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    target_language: Literal["en", "hi", "bn", "pa", "ta", "te", "mr", "gu", "kn", "ml", "or"]


class TranslateResponse(BaseModel):
    translated_text: str
    success: bool
    error: Optional[str] = ""


@router.post("/chat/translate", response_model=TranslateResponse, dependencies=[Depends(require_admin)])
async def translate_endpoint(request: TranslateRequest):
    """
    Translate English text to a supported Indic language. Admin-only: the web
    app never calls it, and an open translation endpoint is a free LLM proxy.
    """
    target = request.target_language
    if target == "en":
        return TranslateResponse(translated_text=request.text, success=True)

    try:
        from src.retrieval.translation_service import TranslationService
        translated = await TranslationService.get_instance().translate_from_english(
            request.text, target
        )
        return TranslateResponse(translated_text=translated, success=True)
    except Exception as e:
        logger.error(f"Semantic translation to {target} failed: {e}")
        return TranslateResponse(translated_text=request.text, success=False, error="Translation failed")
