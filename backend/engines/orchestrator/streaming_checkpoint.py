"""Write-ahead checkpoint for LLM streaming calls.

Saves LLM request params before each streaming invocation so the
orchestrator can detect incomplete attempts on restart and either
retry or skip.  Checkpoints are cleared on successful completion.

Usage::

    ckpt = StreamingCheckpoint(checkpoint_dir="/tmp/ckpt")
    token = ckpt.begin(params)
    try:
        result = executor.execute(params, event_stream)
        ckpt.commit(token)
    except Exception:
        # On next startup, ckpt.recover() returns the uncommitted params
        raise
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from backend.core.logger import forge_logger as logger


@dataclass
class CheckpointRecord:
    """Immutable record of an in-flight LLM call."""

    token: str
    created_at: float
    params_summary: dict[str, Any] = field(default_factory=dict)
    attempt: int = 1


class StreamingCheckpoint:
    """Write-ahead checkpoint manager for LLM streaming calls.

    One active checkpoint at a time per session.  ``begin()`` writes a
    JSON marker to disk; ``commit()`` removes it.  On recovery,
    ``recover()`` returns any uncommitted record so callers can decide
    to retry or discard.
    """

    _FILENAME = "streaming_wal.json"
    _MAX_CHECKPOINT_AGE_SEC: float = 300.0  # 5 minutes

    def __init__(self, checkpoint_dir: str) -> None:
        self._dir = Path(checkpoint_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._wal_path = self._dir / self._FILENAME
        self._active: CheckpointRecord | None = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def begin(self, params: dict[str, Any], attempt: int = 1) -> str:
        """Create a write-ahead checkpoint before an LLM call.

        Returns a unique token used to commit or discard the checkpoint.
        """
        token = uuid.uuid4().hex[:12]
        summary = self._summarise_params(params)
        record = CheckpointRecord(
            token=token,
            created_at=time.time(),
            params_summary=summary,
            attempt=attempt,
        )
        self._write(record)
        self._active = record
        logger.debug("Streaming checkpoint created: %s", token)
        return token

    def commit(self, token: str) -> None:
        """Mark the LLM call as successfully completed — removes the WAL."""
        if self._active and self._active.token != token:
            logger.warning(
                "Commit token mismatch: expected %s, got %s",
                self._active.token,
                token,
            )
        self._remove_wal()
        self._active = None
        logger.debug("Streaming checkpoint committed: %s", token)

    def discard(self) -> None:
        """Explicitly abandon the active checkpoint."""
        self._remove_wal()
        self._active = None

    def recover(self) -> CheckpointRecord | None:
        """Check for an uncommitted checkpoint from a previous run.

        Returns the record if one exists (indicating a crash mid-stream),
        or ``None`` if the last call completed cleanly.
        """
        if not self._wal_path.exists():
            return None
        try:
            raw = json.loads(self._wal_path.read_text(encoding="utf-8"))
            record = CheckpointRecord(**raw)
            age = time.time() - record.created_at

            # Discard stale checkpoints — if the WAL is older than the
            # max age it almost certainly belongs to a completed call
            # whose commit() was missed, not to an in-flight request.
            if age > self._MAX_CHECKPOINT_AGE_SEC:
                logger.warning(
                    "Discarding stale streaming checkpoint %s (age=%.1fs > %.0fs limit)",
                    record.token,
                    age,
                    self._MAX_CHECKPOINT_AGE_SEC,
                )
                self._remove_wal()
                return None

            logger.warning(
                "Recovered uncommitted streaming checkpoint %s (age=%.1fs, attempt=%d)",
                record.token,
                age,
                record.attempt,
            )
            return record
        except Exception:
            logger.exception("Corrupt streaming WAL — discarding")
            self._remove_wal()
            return None

    @property
    def active_token(self) -> str | None:
        return self._active.token if self._active else None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _summarise_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Extract a small summary of params for diagnostics (not full messages)."""
        summary: dict[str, Any] = {}
        if "model" in params:
            summary["model"] = params["model"]
        if "messages" in params:
            summary["message_count"] = len(params["messages"])
        if "tools" in params:
            summary["tool_count"] = len(params["tools"])
        return summary

    def _write(self, record: CheckpointRecord) -> None:
        try:
            self._wal_path.write_text(
                json.dumps(asdict(record), default=str),
                encoding="utf-8",
            )
        except OSError:
            logger.exception("Failed to write streaming WAL")

    def _remove_wal(self) -> None:
        try:
            self._wal_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Failed to remove streaming WAL")
