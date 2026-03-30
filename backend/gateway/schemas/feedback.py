"""Data structures and helpers for storing user feedback about conversations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from backend.core.logger import app_logger as logger
from backend.core.pydantic_compat import model_dump_with_options


@dataclass
class FeedbackDataModel:
    """Feedback record captured from UI submissions about the agent run."""

    session_id: str
    email: str | None = None
    version: str | None = None
    permissions: str | None = None
    polarity: str | None = None
    feedback: str | None = None
    trajectory: list[dict[str, Any]] | None = None


FEEDBACK_URL = "https://share-od-trajectory-3u9bw9tx.uc.gateway.dev/share_od_trajectory"


def store_feedback(feedback: FeedbackDataModel) -> dict[str, str]:
    """Store user feedback to remote endpoint.

    Sends feedback data to feedback collection service, eliding sensitive fields in logs.

    Args:
        feedback: Feedback data to store

    Returns:
        Response data dictionary from feedback service

    Raises:
        ValueError: If feedback storage fails

    """
    feedback.feedback = feedback.polarity
    display_feedback = model_dump_with_options(feedback)
    if "trajectory" in display_feedback:
        display_feedback["trajectory"] = (
            f"elided [length: {len(display_feedback['trajectory'])}"
        )
    if "token" in display_feedback:
        display_feedback["token"] = "elided"
    logger.debug("Got feedback: %s", display_feedback)
    response = httpx.post(
        FEEDBACK_URL,
        headers={"Content-Type": "application/json"},
        json=model_dump_with_options(feedback),
    )
    if response.status_code != 200:
        msg = f"Failed to store feedback: {response.text}"
        raise ValueError(msg)
    response_data: dict[str, str] = json.loads(response.text)
    logger.debug("Stored feedback: %s", response.text)
    return response_data
