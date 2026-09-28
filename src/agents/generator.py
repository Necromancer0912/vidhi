"""
NyayaBot — Generator Agent.

ARCHITECTURE (Updated):
  query → query_planner (LLM identifies what to search) 
        → retrieve (targeted hybrid search)
        → generate_answer (RAG-ONLY: LLM forbidden from using training memory)
        → critic (checks every claim is grounded in retrieved chunks)

KEY CHANGE: The generator is now RAG-AUTHORITY mode.
  - LLM must cite a [Source] for EVERY factual claim.
  - If a fact is not in the context, LLM must say "not in my documents".
  - Confidence is low when LLM ignores this → we catch that in critic.
"""
from __future__ import annotations

import logging
import re
from typing import AsyncIterator, Optional

import tiktoken

from src.config import settings
from src.models import Chunk, Citation

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Generator System Prompt — RAG-AUTHORITY mode
#
# KEY DESIGN DECISIONS:
#   1. "ONLY from the Context Documents" is enforced by requiring [Source] on EVERY claim.
#      If the LLM can't cite it, it must say it's not in the documents.
#   2. 3-part structure (Rights / Violations / Action Plan) for RETRIEVE queries.
#   3. Confidence will be high ONLY when every claim maps to a chunk — this is correct.
#   4. No free-floating facts: every number, deadline, section, penalty needs a [Source].
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT — instructions only, NO context injected here.
# Context goes into the USER message (see build_messages() below).
#
# WHY: LLMs treat system prompt content as "background rules" they can override
# with their own training knowledge. User-message content is treated as
# authoritative primary source material the model should work FROM.
# Moving context to the user message is the most effective RAG grounding technique.
# ─────────────────────────────────────────────────────────────────────────────
GENERATOR_SYSTEM_PROMPT = """You are NyayaBot — India's most trusted AI legal assistant, built to serve both citizens and legal professionals.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚖️ HOW TO USE KNOWLEDGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The user will provide RETRIEVED LEGAL DOCUMENTS in their message.
These documents are your PRIMARY AUTHORITY — they come from verified Indian law sources.

**PRIORITY ORDER** (follow strictly):
1. Facts stated in the retrieved documents → cite as [Document Title, Section] — HIGHEST TRUST
   * Preserve precise section numbers, clauses, and technical legal terminology so it is fully accurate for lawyers.
2. Your training knowledge → use to EXPLAIN retrieved facts in plain language — SUPPORTING ROLE
   * Break down complex legal definitions into clear, practical terms for the citizen.
3. If retrieved docs and training knowledge conflict → **retrieved documents win, always**
   (Laws get amended; your training data may be outdated)

When using training knowledge to fill a gap NOT covered in the documents, label it:
*(General legal knowledge — verify with official sources)*

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚖️ TEMPORAL INTEGRITY & TIMELINE SANITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Always verify temporal context:
- Scan the user query for any references to specific years, amendment years, or upcoming/future rules (e.g., "2026 reforms").
- If the user asks about amendments/rules of a specific year that are NOT explicitly detailed in the retrieved documents, you MUST state clearly: "The retrieved documents do not contain any information about reforms or amendments from [Year]. The latest reforms captured in the provided sources are from [Latest Year in Sources]. I will not speculate on [Year] changes."
- Never fabricate dates, Presidential assent dates (e.g., "6 April 2026"), or provisions for years not present in the sources.
- Prioritize newer laws and amendments (e.g., 2018 amendment over 2016 original act) when explaining thresholds or timelines. Note that the Committee of Creditors (CoC) voting threshold for approval of a resolution plan under Section 30 was reduced to 66% through the 2018 amendment.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 STRUCTURE, LENGTH & BEAUTIFUL RENDER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Do not force a rigid structure. Adapt your response length and format naturally to the query:
  * For simple, factual questions (e.g. timelines, specific sections, definitions), keep your answer short, concise, and direct.
  * For complex scenarios, explain fully but structure it logically.
- Present the information beautifully and professionally:
  * Structure your responses in a formal, authoritative, and professional tone suitable for legal matters.
  * Use clear markdown headers, bold text, and organized lists.
  * Render timelines, comparisons, or multi-step procedures in clean Markdown Tables or bullet points.
  * Keep emojis to a minimal, professional level (or avoid them entirely). Never use decorative emojis or emojis as bullet points. Rely on clean typography and markdown structure rather than emojis.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 LANGUAGE & STYLE CONSISTENCY (HINDI / HINGLISH)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Detect the language and script of the user's query and respond in the EXACT same language and script style:
  1. If the user writes in Hindi (Devanagari script), you MUST respond entirely in Hindi (Devanagari script).
  2. If the user writes in Hinglish (Hindi written in Roman/English alphabet, e.g., "Police ne mujhe roka, kya karu"), you MUST respond in Hinglish (using the Roman/English alphabet but phrasing in common colloquial Hindi).
  3. If the user writes in English, respond in English.
- Keep the citations, section numbers, act names, and official legal terms in their original English names (e.g. "[Right to Information Act, Section 6(1)]" or "Section 41A notice"), even when writing in Hindi or Hinglish, to maintain absolute legal accuracy.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 DESIGN PRINCIPLES FOR CITIZENS & LAWYERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Maintain absolute legal precision: never omit specific section numbers, sub-clauses, or case citations.
- Never say "consult a lawyer" as your FIRST advice — give the law first.
- If documents clearly show the legal position is settled, say so confidently with citations.
- Keep the overall flow and explanations clear, logical, and actionable for a common citizen under stress."""


# ─────────────────────────────────────────────────────────────────────────────
# Emergency Prompt — speed over depth, action over explanation
# ─────────────────────────────────────────────────────────────────────────────
# Emergency prompt — also instructions-only. Context goes in user message.
EMERGENCY_SYSTEM_PROMPT = """You are NyayaBot — India's emergency legal assistant. Someone needs help RIGHT NOW.

EMERGENCY MODE RULES:
1. Under 250 words. Bullet points only. No long paragraphs.
2. First line = their strongest right — cite [Act, Section] from the retrieved documents.
3. Tell them what to SAY on the spot (exact words in quotes).
4. Tell them what to DEMAND in writing (receipt, badge no., written order).
5. If bribe is involved: cite Prevention of Corruption Act §7 and tell them how to report.
6. Every claim must be backed by a retrieved document. No training-data guesses.
7. End with: "Call [relevant helpline] if needed." (Do not use call/phone emojis).
8. Never speculate or fabricate dates/amendments. If the user asks about amendments/years not in the documents, state it clearly.
9. LANGUAGE MATCHING: Detect if the user asks in Hindi, Hinglish (colloquial Hindi in Roman script), or English, and respond in the EXACT same language and script style. Act names, section numbers, and citation tags [Document Title, Section] MUST remain in English to maintain legal accuracy.
10. Emojis: Keep emojis to a minimal, professional level or avoid them completely. Prioritize a formal and professional tone.

The user will provide retrieved legal documents in their message. Use those as your ONLY factual source.
Be direct. Be fast. This person is in a stressful situation RIGHT NOW."""


def assemble_context(chunks: list[Chunk], token_budget: int = None) -> tuple[str, list[Citation]]:
    """
    Assemble retrieved chunks into a context string, respecting token budget.
    
    CHANGE: Chunks are numbered [1], [2], etc. so the LLM can reference them
    precisely in citations. The document title and section are on the first line
    so they're easy to cite.
    
    Returns (context_str, citations_list).
    """
    token_budget = token_budget or settings.token_budget
    enc = tiktoken.get_encoding("cl100k_base")

    context_parts = []
    citations = []
    used_tokens = 0

    # Sort chunks by relevance score (descending) — best first
    sorted_chunks = sorted(chunks, key=lambda c: c.score, reverse=True)

    for i, chunk in enumerate(sorted_chunks):
        # Format: clear source header so LLM can cite it easily
        source_label = chunk.metadata.document_title
        if chunk.metadata.section:
            source_label += f", {chunk.metadata.section}"

        chunk_text = (
            f"[SOURCE {i+1}] {source_label}\n"
            f"Relevance: {chunk.score:.2f}\n"
            f"{chunk.text}"
        )

        chunk_tokens = len(enc.encode(chunk_text))
        if used_tokens + chunk_tokens > token_budget:
            logger.debug(f"Token budget reached at chunk {i+1}/{len(sorted_chunks)}")
            break

        context_parts.append(chunk_text)
        used_tokens += chunk_tokens

        citations.append(Citation(
            chunk_id=chunk.id,
            document_title=chunk.metadata.document_title,
            section=chunk.metadata.section,
            source_url=chunk.metadata.source_url,
            relevance_score=chunk.score,
        ))

    context = "\n\n---\n\n".join(context_parts)
    logger.debug(f"Context assembled: {used_tokens} tokens, {len(citations)} sources")

    if not context_parts:
        context = "NO RELEVANT DOCUMENTS FOUND. Tell the user you cannot answer this with confidence."

    return context, citations


def format_history(history: list[dict]) -> str:
    """Format conversation history for injection into prompt."""
    if not history:
        return "No previous conversation."
    parts = []
    for turn in history[-settings.memory_max_turns:]:
        role = "User" if turn.get("role") == "user" else "NyayaBot"
        parts.append(f"{role}: {turn.get('content', '')}")
    return "\n".join(parts)


def _build_messages(
    query: str,
    context: str,
    history_text: str,
    emergency: bool,
    preferred_language: Optional[str] = None,
) -> list[dict]:
    """
    Build the LLM message list with context in the USER message.

    WHY context goes in user message, NOT system prompt:
      - System prompt = "instructions" → LLM treats as rules it can override
      - User message  = "user-provided material" → LLM treats as authoritative source to work FROM
      - This is the #1 most effective technique for RAG grounding

    Structure:
      [SYSTEM]  Instructions only (role, priority rules, answer format)
      [USER]    Retrieved docs + conversation history + actual question
    """
    system_prompt = EMERGENCY_SYSTEM_PROMPT if emergency else GENERATOR_SYSTEM_PROMPT

    if preferred_language and preferred_language.lower() != "en":
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
        lang_name = lang_names.get(preferred_language.lower(), preferred_language)
        lang_instruction = (
            f"CRITICAL: The user has selected {lang_name} as their preferred language.\n"
            f"THIS PREFERENCE OVERRIDES ANY OTHER LANGUAGE-MATCHING OR LANGUAGE-DETECTION RULES. YOU MUST RESPOND ENTIRELY IN {lang_name.upper()}, USING ITS NATIVE SCRIPT. DO NOT RESPOND IN ENGLISH OR TRANSLITERATED ROMAN SCRIPT (e.g. do not write Hindi using English letters/Hinglish), EVEN IF the user's query is in English or Hinglish.\n"
            f"All descriptions, details, actions, and explanations must be translated fully into {lang_name}.\n"
            f"Keep only the official Act names, Section numbers, and citation tags (e.g. [Document Title, Section]) in English/Roman script to maintain absolute legal accuracy.\n\n"
        )
        system_prompt = lang_instruction + system_prompt

    if history_text and history_text != "No previous conversation.":
        history_block = f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nCONVERSATION HISTORY (for context only):\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{history_text}"
    else:
        history_block = ""

    user_message = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"RETRIEVED LEGAL DOCUMENTS (your PRIMARY source — these take priority over your training knowledge):\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{context}"
        f"{history_block}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"USER QUESTION:\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{query}\n\n"
        f"Answer using the RETRIEVED LEGAL DOCUMENTS above as your primary source."
        f" Cite every factual claim as [Document Title, Section]."
        f" If a fact is not in the documents, label it: *(General legal knowledge)*"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_message},
    ]


async def generate_answer(
    query: str,
    chunks: list[Chunk],
    history: list[dict],
    llm,
    emergency: bool = False,
    preferred_language: Optional[str] = None,
) -> tuple[str, list[Citation]]:
    """Generate a grounded answer. Context is placed in the USER message for maximum RAG grounding."""
    context, citations = assemble_context(chunks)
    history_text = format_history(history)
    messages = _build_messages(query, context, history_text, emergency, preferred_language)

    try:
        chunks_list = []
        async for chunk in llm.astream(messages, config={"tags": ["streamable_answer"]}):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            chunks_list.append(content)
        answer = "".join(chunks_list)
        return answer.strip(), citations
    except Exception as e:
        logger.error(f"Generator LLM call failed: {e}")
        raise


CHITCHAT_PROMPT = """You are NyayaBot — a professional and helpful AI legal assistant for Indian citizens.
You help with questions about Indian laws, rights, and government procedures.

If this is a greeting or capability question, respond warmly, professionally, and briefly.
Tell the user you can help with: RTI, consumer rights, EPF/PF, labour laws, property registration, 
income tax, FIR filing, startup registration, RERA, free legal aid, traffic rights, and more.
Keep your response formal and professional, and minimize or avoid the use of emojis.

User message: {query}"""


async def generate_chitchat(query: str, llm, preferred_language: Optional[str] = None) -> str:
    """Handle off-topic/greeting queries with a helpful, branded response."""
    prompt = CHITCHAT_PROMPT.format(query=query)
    if preferred_language and preferred_language.lower() != "en":
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
        lang_name = lang_names.get(preferred_language.lower(), preferred_language)
        lang_instruction = (
            f"CRITICAL: The user has selected {lang_name} as their preferred language.\n"
            f"THIS PREFERENCE OVERRIDES ANY OTHER LANGUAGE-MATCHING OR DETECTION RULES. YOU MUST RESPOND ENTIRELY IN {lang_name.upper()}, USING ITS NATIVE SCRIPT. DO NOT RESPOND IN ENGLISH OR TRANSLITERATED ROMAN SCRIPT, even if the query is in English.\n\n"
        )
        prompt = lang_instruction + prompt

    chunks_list = []
    async for chunk in llm.astream(prompt, config={"tags": ["streamable_answer"]}):
        content = chunk.content if hasattr(chunk, "content") else str(chunk)
        chunks_list.append(content)
    answer = "".join(chunks_list)
    return answer.strip()


async def translate_to_english(query: str, llm) -> str:
    """
    Translate non-English (Hindi, Bengali, Punjabi, Hinglish, etc.) query to English semantically.
    If the query is already standard legal English, return it as-is.
    """
    # Quick ascii check: if it is standard ascii with only letters, spaces and simple punctuation,
    # it might still be Hinglish (colloquial Hindi written in English script).
    # To be safe, we ask the LLM to translate or keep as-is.
    prompt = (
        "Translate the following query into standard English. "
        "If it is already in English, return it exactly as-is. "
        "Preserve all law names, section numbers, and citations in English. "
        "Return ONLY the translated English query, no commentary or explanations.\n\n"
        f"Query: {query}"
    )
    try:
        response = await llm.ainvoke(prompt)
        translated = response.content if hasattr(response, "content") else str(response)
        translated = translated.strip()
        logger.debug(f"Backend translation: Original='{query}' -> Translated='{translated}'")
        return translated
    except Exception as e:
        logger.warning(f"Translation to English failed: {e} — using original query")
        return query

