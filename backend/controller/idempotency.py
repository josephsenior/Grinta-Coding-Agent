"""Idempotency tagging and deduplication for agent actions.

Assigns a content-based idempotency key to each action so the pipeline
can detect and skip re-execution of identical tool calls within the
same session.

The key is a hash of the action type + its serialisable content, meaning
two identical ``CmdRunAction(command="ls -la")`` calls produce the same
key.  The middleware maintains a sliding window of recently executed keys
and blocks duplicates within a configurable TTL.

Usage::

    from backend.controller.idempotency import IdempotencyMiddleware

    # Add to the tool invocation pipeline
    pipeline.middlewares.append(IdempotencyMiddleware())
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from backend.controller.tool_pipeline import (
    ToolInvocationContext,
    ToolInvocationMiddleware,
)
from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    pass

# Action types that are inherently non-idempotent (side-effect-free reads
# are always safe to repeat).
_NON_IDEMPOTENT_ACTIONS: set[str] = {
    "CmdRunAction",
    "IPythonRunCellAction",
    "FileWriteAction",
    "FileEditAction",
}

# Commands that are effectively read-only or verification commands.
# These should never be blocked by idempotency even if they repeat,
# because their purpose is to observe state that may have changed.
_READ_ONLY_COMMAND_PATTERNS: tuple[str, ...] = (
    "pytest", "python -m pytest", "npm test", "yarn test",
    "make test", "go test", "cargo test",
    "cat ", "head ", "tail ", "grep ", "rg ",
    "ls ", "find ", "tree ", "wc ",
    "git status", "git diff", "git log",
    "python -c", "node -e",
)

# Action types that are always idempotent / safe to repeat.
_IDEMPOTENT_ACTIONS: set[str] = {
    "FileReadAction",
    "BrowseURLAction",
    "AgentThinkAction",
    "MessageAction",
}


def compute_idempotency_key(action: Any) -> str:
    """Compute a content-based idempotency key for an action.

    The key is ``sha256(action_class_name + sorted_fields)``.
    """
    parts: list[str] = [type(action).__name__]
    # Use dataclass fields if available, otherwise __dict__
    fields = getattr(action, "__dataclass_fields__", None)
    if fields:
        for fname in sorted(fields):
            val = getattr(action, fname, "")
            # Skip volatile fields
            if fname in ("_id", "_timestamp", "_source", "_cause", "source"):
                continue
            parts.append(f"{fname}={val}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def classify_idempotency(action: Any) -> str:
    """Classify an action's idempotency level.

    Returns:
        ``"idempotent"`` — safe to repeat any number of times.
        ``"non-idempotent"`` — has side effects, should not be repeated.
        ``"unknown"`` — not classified, treated as non-idempotent by default.
    """
    name = type(action).__name__
    if name in _IDEMPOTENT_ACTIONS:
        return "idempotent"
    if name in _NON_IDEMPOTENT_ACTIONS:
        return "non-idempotent"
    return "unknown"


class IdempotencyMiddleware(ToolInvocationMiddleware):
    """Pipeline middleware that blocks duplicate non-idempotent tool calls.

    Maintains a bounded LRU cache of recently executed idempotency keys.
    Duplicate *non-idempotent* actions within ``ttl_seconds`` are blocked;
    idempotent actions are always allowed through.
    """

    def __init__(
        self,
        max_cache_size: int = 200,
        ttl_seconds: float = 120.0,
    ) -> None:
        self._cache: OrderedDict[str, float] = OrderedDict()
        self._max_size = max_cache_size
        self._ttl = ttl_seconds

    async def plan(self, ctx: ToolInvocationContext) -> None:
        key = compute_idempotency_key(ctx.action)
        classification = classify_idempotency(ctx.action)

        # Store classification & key in metadata for downstream stages
        ctx.metadata["idempotency_key"] = key
        ctx.metadata["idempotency_class"] = classification

        if classification == "idempotent":
            return  # Always allow

        # CmdRunAction: allow read-only/verification commands to repeat freely.
        # After an edit, re-running `pytest` or `cat file.py` is intentional.
        action_name = type(ctx.action).__name__
        if action_name == "CmdRunAction":
            cmd = getattr(ctx.action, "command", "")
            cmd_stripped = cmd.strip()
            if any(cmd_stripped.startswith(pat) for pat in _READ_ONLY_COMMAND_PATTERNS):
                return  # Always allow verification/read commands

        # Check for recent duplicate
        now = time.monotonic()
        self._evict_expired(now)

        if key in self._cache:
            elapsed = now - self._cache[key]
            if elapsed < self._ttl:
                logger.info(
                    "Idempotency guard: blocking duplicate %s (key=%s, age=%.1fs)",
                    type(ctx.action).__name__,
                    key[:12],
                    elapsed,
                )
                ctx.block(reason=f"duplicate_action:{key[:12]}")
                return

        # Record this execution
        self._cache[key] = now
        self._cache.move_to_end(key)
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def _evict_expired(self, now: float) -> None:
        """Remove entries older than TTL from the front of the LRU."""
        while self._cache:
            _, oldest_ts = next(iter(self._cache.items()))
            if now - oldest_ts > self._ttl:
                self._cache.popitem(last=False)
            else:
                break
