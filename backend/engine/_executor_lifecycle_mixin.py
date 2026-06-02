"""Lifecycle methods for OrchestratorExecutor: preflight, checkpoint, async execute.

Pure code motion: extracted from backend/engine/executor.py. Methods defined
at module level for clean extraction.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.core.constants import (
    DEFAULT_AGENT_STREAMING_CHECKPOINT_DISCARD_STALE_ON_RECOVERY,
    DEFAULT_AGENT_STREAMING_CHECKPOINT_MAX_AGE_SECONDS,
)
from backend.core.logger import app_logger as logger
from backend.engine._executor_types import _MAX_CHECKPOINT_CACHE_SIZE
from backend.engine.streaming_checkpoint import (
    StreamingCheckpoint,
    StreamingCheckpointRecoveryError,
)
from backend.ledger.persistence import EventPersistence

if TYPE_CHECKING:
    from backend.ledger.stream import EventStream


class _ExecutorLifecycleMixin:
    """Mixin: preflight, checkpoint, async lifecycle. All 18 methods defined below."""

    def _apply_context_window_preflight(
        self, call_params: dict[str, Any]
    ) -> dict[str, Any]:
        from backend.inference.exceptions import ContextWindowExceededError

        input_limit = self._llm_input_token_limit()
        output_limit = self._llm_output_token_limit()

        total_limit = 0
        context_window = getattr(self._llm, 'context_window', None)
        if callable(context_window):
            with contextlib.suppress(Exception):
                total_limit = self._positive_int(context_window()) or 0
        if total_limit <= 0:
            if input_limit > 0 and output_limit is not None:
                total_limit = input_limit + output_limit
            else:
                total_limit = input_limit

        if input_limit <= 0 and total_limit <= 0:
            return call_params

        prompt_tokens = self._estimate_request_tokens(call_params)
        model_name = self._llm_model_name(self._llm) or 'unknown'
        margin = self._preflight_margin(total_limit or input_limit)
        input_margin = min(margin, 256)

        if input_limit > 0 and prompt_tokens >= max(input_limit - input_margin, 1):
            raise ContextWindowExceededError(
                'Preflight context guard rejected the request: estimated prompt '
                f'({prompt_tokens}) exceeds the safe input budget for {model_name}.'
            )

        if total_limit <= 0:
            return call_params

        available_completion = total_limit - prompt_tokens - margin
        if available_completion < self._minimum_viable_completion_tokens():
            raise ContextWindowExceededError(
                'Preflight context guard rejected the request: not enough token '
                f'budget remains for a usable completion on {model_name}.'
            )

        field_name, requested_completion = self._preflight_completion_field(call_params)
        desired_completion = requested_completion
        if output_limit is not None:
            desired_completion = (
                output_limit
                if desired_completion is None
                else min(desired_completion, output_limit)
            )

        if desired_completion is None:
            desired_completion = available_completion
        elif desired_completion > available_completion:
            logger.warning(
                'Clamping completion budget from %d to %d tokens for %s to stay within the context window',
                desired_completion,
                available_completion,
                model_name,
            )
            desired_completion = available_completion

        guarded = dict(call_params)
        guarded[field_name] = desired_completion
        return guarded

    @staticmethod
    def _checkpoint_anchor_event_id(event_stream: EventStream | None) -> int | None:
        if event_stream is None:
            return None
        try:
            latest = event_stream.get_latest_event_id()
        except Exception:
            return None
        return latest if isinstance(latest, int) and latest >= 0 else None

    def _checkpoint_is_superseded_by_persisted_control_event(
        self,
        event_stream: EventStream | None,
        record: Any,
    ) -> bool:
        if event_stream is None or record is None:
            return False
        anchor_event_id = getattr(record, 'anchor_event_id', None)
        if not isinstance(anchor_event_id, int) or anchor_event_id < 0:
            return False
        latest_critical_id = self._latest_persisted_critical_event_id(event_stream)
        return latest_critical_id is not None and latest_critical_id > anchor_event_id

    def _checkpoint_recovery_policy(self) -> tuple[float, bool]:
        config = getattr(self._planner, '_config', None)

        max_checkpoint_age_sec = DEFAULT_AGENT_STREAMING_CHECKPOINT_MAX_AGE_SECONDS
        configured_max_age = getattr(
            config,
            'streaming_checkpoint_max_age_seconds',
            max_checkpoint_age_sec,
        )
        if (
            isinstance(configured_max_age, int | float)
            and not isinstance(configured_max_age, bool)
            and configured_max_age > 0
        ):
            max_checkpoint_age_sec = float(configured_max_age)

        discard_stale_on_recovery = (
            DEFAULT_AGENT_STREAMING_CHECKPOINT_DISCARD_STALE_ON_RECOVERY
        )
        configured_discard_stale = getattr(
            config,
            'streaming_checkpoint_discard_stale_on_recovery',
            discard_stale_on_recovery,
        )
        if isinstance(configured_discard_stale, bool):
            discard_stale_on_recovery = configured_discard_stale

        return max_checkpoint_age_sec, discard_stale_on_recovery

    @staticmethod
    def _checkpoint_session_key(event_stream: EventStream | None) -> str:
        sid = getattr(event_stream, 'sid', None)
        return sid if isinstance(sid, str) and sid else '__global__'

    def _estimate_request_tokens(self, call_params: dict[str, Any]) -> int:
        from backend.inference.llm_utils import get_token_count

        model = self._llm_model_name(self._llm) or 'gpt-4o'
        messages = call_params.get('messages') or []
        prompt_tokens = get_token_count(messages, model=model)

        extra_lines: list[str] = []
        for key in sorted(call_params.keys()):
            if key in {
                'messages',
                'stream',
                'max_tokens',
                'max_completion_tokens',
            }:
                continue
            value = call_params.get(key)
            if value is None:
                continue
            extra_lines.append(f'{key}:{self._serialize_preflight_payload(value)}')

        if not extra_lines:
            return prompt_tokens

        extra_tokens = get_token_count(
            [{'role': 'system', 'content': '\n'.join(extra_lines)}],
            model=model,
        )
        return prompt_tokens + extra_tokens

    def _get_checkpoint(self, event_stream: EventStream | None) -> StreamingCheckpoint:
        session_key = self._checkpoint_session_key(event_stream)
        checkpoint = self._checkpoint_cache.get(session_key)
        if checkpoint is not None:
            self._checkpoint_cache.move_to_end(session_key)
            return checkpoint

        if event_stream is None:
            checkpoint_dir = self._checkpoint_root
        else:
            checkpoint_dir = os.path.join(
                self._checkpoint_root,
                self._sanitize_checkpoint_key(session_key),
            )

        max_checkpoint_age_sec, discard_stale_on_recovery = (
            self._checkpoint_recovery_policy()
        )

        checkpoint = StreamingCheckpoint(
            checkpoint_dir,
            max_checkpoint_age_sec=max_checkpoint_age_sec,
            discard_stale_on_recovery=discard_stale_on_recovery,
        )
        inspection = checkpoint.inspect_recovery()
        if inspection.status in {'blocked_uncommitted', 'blocked_stale'}:
            if self._checkpoint_is_superseded_by_persisted_control_event(
                event_stream,
                inspection.record,
            ):
                checkpoint.discard()
                logger.warning(
                    'Discarded stale streaming checkpoint for %s because a newer persisted control event proves the session advanced',
                    session_key,
                )
            else:
                raise StreamingCheckpointRecoveryError(
                    'Uncommitted streaming checkpoint blocks automatic continuation '
                    f'for {session_key}: {inspection.reason}. '
                    'Inspect the checkpoint or persisted ledger before retrying.'
                )
        self._checkpoint_cache[session_key] = checkpoint
        self._checkpoint_cache.move_to_end(session_key)
        while len(self._checkpoint_cache) > _MAX_CHECKPOINT_CACHE_SIZE:
            evicted_key, evicted_ckpt = self._checkpoint_cache.popitem(last=False)
            try:
                evicted_ckpt.discard()
            except Exception:
                pass
            logger.debug(
                'Evicted streaming checkpoint for %s (cache full)', evicted_key
            )
        return checkpoint

    @staticmethod
    def _latest_persisted_critical_event_id(
        event_stream: EventStream,
    ) -> int | None:
        try:
            for event in event_stream.search_events(reverse=True):
                if not EventPersistence.is_critical_event(event):
                    continue
                event_id = getattr(event, 'id', None)
                if isinstance(event_id, int) and event_id >= 0:
                    return event_id
        except Exception as exc:
            logger.debug(
                'Failed to inspect persisted critical events for %s: %s',
                getattr(event_stream, 'sid', '<unknown>'),
                exc,
            )
        return None

    def _llm_input_token_limit(self) -> int:
        llm = self._llm
        features = getattr(llm, 'features', None)
        config = getattr(llm, 'config', None)

        max_in = self._positive_int(getattr(features, 'max_input_tokens', None))
        if max_in is not None:
            return max_in

        max_in = self._positive_int(getattr(config, 'max_input_tokens', None))
        if max_in is not None:
            return max_in

        context_window = getattr(llm, 'context_window', None)
        if callable(context_window):
            with contextlib.suppress(Exception):
                fallback = self._positive_int(context_window())
                if fallback is not None:
                    return fallback
        return 0

    @staticmethod
    def _llm_model_name(llm: Any) -> str | None:
        model = getattr(getattr(llm, 'config', None), 'model', None)
        if isinstance(model, str) and model.strip():
            return model
        return None

    def _llm_output_token_limit(self) -> int | None:
        llm = self._llm
        features = getattr(llm, 'features', None)
        config = getattr(llm, 'config', None)

        max_out = self._positive_int(getattr(features, 'max_output_tokens', None))
        if max_out is not None:
            return max_out

        return self._positive_int(getattr(config, 'max_output_tokens', None))

    @staticmethod
    def _minimum_viable_completion_tokens() -> int:
        return 64

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, float):
            iv = int(value)
            return iv if iv > 0 else None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            with contextlib.suppress(ValueError):
                iv = int(stripped)
                return iv if iv > 0 else None
        return None

    @staticmethod
    def _preflight_completion_field(
        call_params: dict[str, Any],
    ) -> tuple[str, int | None]:
        if 'max_completion_tokens' in call_params:
            return 'max_completion_tokens', _ExecutorLifecycleMixin._positive_int(
                call_params.get('max_completion_tokens')
            )
        if 'max_tokens' in call_params:
            return 'max_tokens', _ExecutorLifecycleMixin._positive_int(
                call_params.get('max_tokens')
            )
        return 'max_tokens', None

    @staticmethod
    def _preflight_margin(limit: int) -> int:
        if limit <= 0:
            return 0
        return max(128, min(1024, limit // 100))

    @staticmethod
    def _sanitize_checkpoint_key(session_key: str) -> str:
        safe = Path(session_key).name.replace('..', '_')
        return safe.replace('/', '_').replace('\\', '_')

    @staticmethod
    def _serialize_preflight_payload(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            return str(value)

    @staticmethod
    def _timeout_from_env(
        env_var: str,
        default: float,
        *,
        allow_disable: bool = False,
    ) -> float | None:
        raw = os.getenv(env_var, str(default)).strip()
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            return default
        if parsed > 0:
            return parsed
        return None if allow_disable else default
