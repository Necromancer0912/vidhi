"""
NyayaBot — Feedback endpoint (thumbs up/down for RLHF data collection).
"""
from __future__ import annotations

import json
import time
import logging

from fastapi import APIRouter, Depends

from src.api.security import limit_by_ip

from src.cache.redis_store import Analytics, redis_client
from src.models import FeedbackRequest

logger = logging.getLogger(__name__)
router = APIRouter()

FEEDBACK_KEY = "nyayabot:feedback"


@router.post("/feedback", dependencies=[Depends(limit_by_ip("feedback", 20))])
def submit_feedback(request: FeedbackRequest):
    """
    Store user feedback for a message.
    Stored in Redis for weekly batch analysis / re-ranking fine-tune.
    """
    try:
        r = redis_client()
        if not r:
            logger.warning("Feedback not stored: Redis client unavailable")
            return {"status": "error", "message": "Redis unavailable"}

        feedback_data = json.dumps({
            "session_id": request.session_id,
            "message_id": request.message_id,
            "thumbs_up": request.thumbs_up,
            "comment": request.comment or "",
            "timestamp": time.time(),
        })
        r.lpush(FEEDBACK_KEY, feedback_data)
        r.ltrim(FEEDBACK_KEY, 0, 9999)  # keep last 10k
        try:
            Analytics().track_feedback(is_positive=request.thumbs_up)
        except Exception as exc:
            logger.debug(f"Feedback analytics failed: {exc}")
        logger.info(f"Feedback stored: {request.thumbs_up} for session {request.session_id}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Feedback store error: {e}")
        return {"status": "error", "message": "Feedback could not be stored"}

