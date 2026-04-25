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

from backend.core.constants import (
    DEFAULT_AGENT_STREAMING_CHECKPOINT_DISCARD_STALE_ON_RECOVERY,
    DEFAULT_AGENT_STREAMING_CHECKPOINT_MAX_AGE_SECONDS,
)
from backend.core.logger import app_logger as logger


@dataclass
class CheckpointRecord:
    """Immutable record of an in-flight LLM call."""

    token: str
    created_at: float
    params_summary: dict[str, Any] = field(default_factory=dict)
    attempt: int = 1
    anchor_event_id: int | None = None


@dataclass
class RecoveryInspection:
    """Result of inspecting the streaming WAL on startup."""

    status: str
    record: CheckpointRecord | None = None
    reason: str = ''


class StreamingCheckpoint:
    """Write-ahead checkpoint manager for LLM streaming calls.

    One active checkpoint at a time per session.  ``begin()`` writes a
    JSON marker to disk; ``commit()`` removes it.  On recovery,
    ``recover()`` returns any uncommitted record so callers can decide
    to retry or discard.
    """

    _FILENAME = 'streaming_wal.json'

    def __init__(
        self,
        checkpoint_dir: str,
        *,
        max_checkpoint_age_sec: float = DEFAULT_AGENT_STREAMING_CHECKPOINT_MAX_AGE_SECONDS,
        discard_stale_on_recovery: bool = DEFAULT_AGENT_STREAMING_CHECKPOINT_DISCARD_STALE_ON_RECOVERY,
    ) -> None:
        if max_checkpoint_age_sec <= 0:
            raise ValueError('max_checkpoint_age_sec must be positive')
        self._dir = Path(checkpoint_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._wal_path = self._dir / self._FILENAME
        self._active: CheckpointRecord | None = None
        self._max_checkpoint_age_sec = float(max_checkpoint_age_sec)
        self._discard_stale_on_recovery = bool(discard_stale_on_recovery)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def begin(
        self,
        params: dict[str, Any],
        attempt: int = 1,
        *,
        anchor_event_id: int | None = None,
    ) -> str:
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
            anchor_event_id=anchor_event_id,
        )
        self._write(record)
        self._active = record
        logger.debug('Streaming checkpoint created: %s', token)
        return token

    def commit(self, token: str) -> None:
        """Mark the LLM call as successfully completed — removes the WAL."""
        if self._active and self._active.token != token:
            logger.warning(
                'Commit token mismatch: expected %s, got %s',
                self._active.token,
                token,
            )
        self._remove_wal()
        self._active = None
        logger.debug('Streaming checkpoint committed: %s', token)

    def discard(self) -> None:
        """Explicitly abandon the active checkpoint."""
        self._remove_wal()
        self._active = None

    def recover(self) -> CheckpointRecord | None:
        """Check for an uncommitted checkpoint from a previous run.

        Returns the record if one exists (indicating a crash mid-stream),
        or ``None`` if the last call completed cleanly.
        """
        inspection = self.inspect_recovery()
        if inspection.status in {'blocked_uncommitted', 'blocked_stale'}:
            return inspection.record
        return None

    def inspect_recovery(self) -> RecoveryInspection:
        """Inspect the WAL and classify recovery state without guessing.

        Recent uncommitted checkpoints are treated as ambiguous and should
        block the next automatic retry. Corrupt or stale WAL files are
        discarded eagerly.
        """
        if not self._wal_path.exists():
            return RecoveryInspection(status='clean')
        try:
            record = self._read_record()
            age = time.time() - record.created_at

            if age > self._max_checkpoint_age_sec:
                if self._discard_stale_on_recovery:
                    reason = (
                        f'checkpoint age {age:.1f}s exceeded '
                        f'{self._max_checkpoint_age_sec:.1f}s max age; '
                        'auto-discard enabled'
                    )
                    logger.warning(
                        'Discarding stale streaming checkpoint %s (%s)',
                        record.token,
                        reason,
                    )
                    self._remove_wal()
                    return RecoveryInspection(
                        status='stale_discarded',
                        record=record,
                        reason=reason,
                    )

                reason = (
                    f'stale uncommitted checkpoint token={record.token} '
                    f'age={age:.1f}s attempt={record.attempt} '
                    f'exceeded {self._max_checkpoint_age_sec:.1f}s max age '
                    'with auto-discard disabled'
                )
                logger.warning('Streaming checkpoint requires manual recovery: %s', reason)
                return RecoveryInspection(
                    status='blocked_stale',
                    record=record,
                    reason=reason,
                )

            reason = (
                f'recent uncommitted checkpoint token={record.token} '
                f'age={age:.1f}s attempt={record.attempt}'
            )
            logger.warning('Streaming checkpoint requires manual recovery: %s', reason)
            return RecoveryInspection(
                status='blocked_uncommitted',
                record=record,
                reason=reason,
            )
        except Exception:
            logger.exception('Corrupt streaming WAL — discarding')
            self._remove_wal()
            return RecoveryInspection(
                status='corrupt_discarded',
                reason='checkpoint WAL could not be parsed',
            )

    @property
    def active_token(self) -> str | None:
        return self._active.token if self._active else None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _summarise_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Extract a small summary of params for diagnostics (not full messages)."""
        summary: dict[str, Any] = {}
        if 'model' in params:
            summary['model'] = params['model']
        if 'messages' in params:
            summary['message_count'] = len(params['messages'])
        if 'tools' in params:
            summary['tool_count'] = len(params['tools'])
        return summary

    def _read_record(self) -> CheckpointRecord:
        raw = json.loads(self._wal_path.read_text(encoding='utf-8'))
        return CheckpointRecord(**raw)

    def _write(self, record: CheckpointRecord) -> None:
        try:
            self._wal_path.write_text(
                json.dumps(asdict(record), default=str),
                encoding='utf-8',
            )
        except OSError:
            logger.exception('Failed to write streaming WAL')

    def _remove_wal(self) -> None:
        try:
            self._wal_path.unlink(missing_ok=True)
        except OSError:
            logger.exception('Failed to remove streaming WAL')
