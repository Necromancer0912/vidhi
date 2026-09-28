"""
NyayaBot — Router Agent.
Classifies incoming queries into: RETRIEVE | MEMORY | TOOL | CHITCHAT.
Uses regex fast-path before expensive LLM call.
"""
from __future__ import annotations

import json
import logging
import re

from src.models import RouteDecision, RouteType

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Regex fast-path rules (evaluated before LLM)
# ─────────────────────────────────────────────
FAST_PATH_RULES: list[tuple[str, RouteType]] = [
    # ── EMERGENCY: on-the-spot legal help (checked FIRST for speed) ────────
    # Traffic / vehicle stops
    (r"police\s*(ne\s*)?stop(ped|p)?\s*(me|us|kar)", RouteType.EMERGENCY),
    (r"(officer|cop|police)\s*(is\s*)?(asking|mang|demand|maang)(ing|\s+raha)?(\s+for)?\s*brib", RouteType.EMERGENCY),
    (r"bribe|ghoos|raswaai|rishwat", RouteType.EMERGENCY),
    (r"i\s*(am|was|got)\s*(being\s*)?arrest(ed)?", RouteType.EMERGENCY),
    (r"(they|police|officer)\s*(is\s*)?threaten(ing)?", RouteType.EMERGENCY),
    (r"(right|abhi|abhi)\s*now\s*(help|legal|kya\s*karu|kya\s*karna)", RouteType.EMERGENCY),
    (r"challan\s*(kaat|cut|kat|diya|de\s*raha|without|no\s*doc)", RouteType.EMERGENCY),
    (r"((license|licence|rc|registration).*(seized|seize|jam|le\s*liya|cheen)|(seized|seize|jam|le\s*liya|cheen).*(license|licence|rc|registration))", RouteType.EMERGENCY),
    (r"what\s*(are|r)\s*my\s*rights\s*(right\s*now|immediately|abhi)", RouteType.EMERGENCY),
    (r"emergency\s*legal|legal\s*emergency", RouteType.EMERGENCY),
    (r"fir\s*(file|darz|likhwa)\s*(nahi|refuse|mana)", RouteType.EMERGENCY),
    (r"police\s*(nahi|not)\s*(likh|register|file|sun)", RouteType.EMERGENCY),
    # ── Court case number patterns ─────────────────────────────────────────
    (r"cnr\s*(number|no\.?)?|case\s*number\s*:\s*[A-Z]{2,}", RouteType.TOOL),
    # eCourts case status
    (r"case\s*status|court\s*date|next\s*hearing", RouteType.TOOL),
    # Memory references
    (r"\b(you\s*said|earlier\s*you|what\s*did\s*you\s*mean|as\s*you\s*mentioned|previously\s*you)\b",
     RouteType.MEMORY),
    # Chitchat
    (r"^(hi|hello|hey|thanks?|thank\s*you|bye|good\s*(morning|evening|night))[!.,\s]*$",
     RouteType.CHITCHAT),
    # Who are you
    (r"who\s*are\s*you|what\s*are\s*you|your\s*name|about\s*you", RouteType.CHITCHAT),
]

ROUTER_SYSTEM_PROMPT = """You are a query classifier for NyayaBot — an AI assistant for Indian citizens 
about legal rights, government procedures, consumer protection, labour laws, tax, property, and more.

Classify the user's query into EXACTLY ONE category:

EMERGENCY: User is in an active, stressful legal situation RIGHT NOW and needs immediate help.
Examples:
- "Police stopped me, what do I do?"
- "Officer is asking for bribe"
- "I am being arrested"
- "They are threatening me"
- "Police stopped us, we have rented car but forgot documents"
- "Challan de raha hai, kya karna chahiye?"
Use EMERGENCY when the person needs to act within minutes, not hours.

RETRIEVE: User wants to understand a law, procedure, or their rights in general.
Examples:
- "How do I file an RTI?"
- "What are my rights if arrested?"
- "How to file consumer complaint?"
- Indian laws, acts, sections, legal procedures
- Government services (PF/EPF, consumer court, property registration, startup)
- Tax filing, income tax, GST procedures

MEMORY: User is referring to something said earlier in this conversation.
Examples: "what did you mean by that", "earlier you said", "clarify your previous answer"

TOOL: User needs real-time external data that is NOT in legal documents.
Examples: "check my case status", "current exchange rate", "today's news"

CHITCHAT: Off-topic, greeting, or capability questions.
Examples: "hello", "what can you do", "thanks"

Respond with ONLY valid JSON:
{"route": "RETRIEVE", "reasoning": "brief reason", "confidence": 0.95}"""


async def route_query(query: str, llm) -> RouteDecision:
    """
    Classify a query into a route type.
    
    1. Check regex fast-path rules
    2. If no fast-path match, call LLM with structured output prompt
    """
    query_lower = query.lower().strip()

    # 1. Fast path: regex rules (instant, no LLM call)
    for pattern, route_type in FAST_PATH_RULES:
        if re.search(pattern, query_lower, re.IGNORECASE):
            logger.debug(f"Fast-path match: {route_type.value} for query: {query[:50]}")
            return RouteDecision(
                route=route_type,
                reasoning="Matched fast-path regex rule",
                confidence=0.99,
            )

    # 2. LLM-based classification
    messages = [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]

    try:
        response = await llm.ainvoke(messages)
        content = response.content if hasattr(response, "content") else str(response)

        # Extract JSON from response
        json_match = re.search(r"\{[^}]+\}", content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return RouteDecision(
                route=RouteType(data.get("route", "RETRIEVE")),
                reasoning=data.get("reasoning", ""),
                confidence=float(data.get("confidence", 0.8)),
            )
    except Exception as e:
        logger.warning(f"Router LLM call failed: {e} — defaulting to RETRIEVE")

    # Default fallback: RETRIEVE (safest for a legal Q&A system)
    return RouteDecision(
        route=RouteType.RETRIEVE,
        reasoning="Fallback to RETRIEVE due to parsing error",
        confidence=0.5,
    )
