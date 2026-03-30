"""Session contract for long-running agent conversations.

The goal is to centralize invariants and normalization logic (cursor semantics,
limits, and health classification) so routes and services stay thin.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SessionHealth(str, Enum):
    healthy = "healthy"
    degraded_readonly = "degraded_readonly"
    degraded_no_persist = "degraded_no_persist"
    broken = "broken"


class PersistenceGuarantee(str, Enum):
    sync = "sync"
    async_best_effort = "async_best_effort"


class BackpressurePolicy(str, Enum):
    drop_oldest = "drop_oldest"
    drop_newest = "drop_newest"
    block = "block"


@dataclass(frozen=True, slots=True)
class ReplayCursor:
    """Replay cursor for trajectory export.

    Semantics:
      - since_id is inclusive lower-bound; server returns events with id > since_id
      - start_id is the normalized first id to read from storage
      - limit caps returned events
    """

    since_id: int | None
    start_id: int
    limit: int


def normalize_replay_cursor(
    *,
    since_id: int | None,
    limit: int | None,
    default_limit: int = 1000,
    max_limit: int = 5000,
) -> ReplayCursor:
    """Normalize query parameters into a stable replay cursor."""
    # Allow operators to tune safe defaults without code changes.
    with_default = os.getenv("APP_TRAJECTORY_DEFAULT_LIMIT")
    if with_default:
        try:
            default_limit = int(with_default)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid APP_TRAJECTORY_DEFAULT_LIMIT=%r; using default %d",
                with_default,
                default_limit,
            )
    start_id = 0
    if since_id is not None:
        start_id = max(0, since_id + 1)

    resolved_limit = default_limit if limit is None else int(limit)
    resolved_limit = max(resolved_limit, 1)
    resolved_limit = min(resolved_limit, max_limit)

    return ReplayCursor(since_id=since_id, start_id=start_id, limit=resolved_limit)
