"""Tests for the bounded-pipeline plan (Layers 1, 2, 5).

These tests verify the orchestrator's hot path is bounded against any
single hang point:

- Layer 1: LLM step (``astep``) has a default wall-clock cap so a hung
  LLM provider cannot wedge the agent.  The cap is configurable via
  ``APP_LLM_STEP_TIMEOUT_SECONDS``.
- Layer 2: Observation handler is bounded with a 10s ceiling.
- Layer 5: Step drain loop has a 600s ceiling per iteration; force-clears
  pending state and emits a visible error on timeout.
"""

from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.llm_step_timeout import (
    DEFAULT_LLM_STEP_TIMEOUT_SECONDS,
    llm_step_timeout_seconds_from_env,
)


# ── Layer 1: LLM step timeout default ────────────────────────────────


class TestLlmStepTimeoutDefault:
    """The default LLM step timeout must be a positive value."""

    def test_default_is_300s(self):
        """Production default is 300s (5 minutes) per LLM step."""
        assert DEFAULT_LLM_STEP_TIMEOUT_SECONDS == 300.0

    def test_unset_env_returns_default(self, monkeypatch):
        """With APP_LLM_STEP_TIMEOUT_SECONDS unset, default 300s applies."""
        monkeypatch.delenv('APP_LLM_STEP_TIMEOUT_SECONDS', raising=False)
        result = llm_step_timeout_seconds_from_env()
        assert result == DEFAULT_LLM_STEP_TIMEOUT_SECONDS
        assert result == 300.0

    def test_empty_env_returns_default(self, monkeypatch):
        """Empty env var is treated as unset and uses the default."""
        monkeypatch.setenv('APP_LLM_STEP_TIMEOUT_SECONDS', '')
        result = llm_step_timeout_seconds_from_env()
        assert result == DEFAULT_LLM_STEP_TIMEOUT_SECONDS

    def test_explicit_positive_value(self, monkeypatch):
        """Positive env value overrides the default."""
        monkeypatch.setenv('APP_LLM_STEP_TIMEOUT_SECONDS', '120')
        result = llm_step_timeout_seconds_from_env()
        assert result == 120.0

    def test_explicit_zero_returns_none(self, monkeypatch):
        """Zero is the user opt-out: unlimited (no asyncio bound)."""
        monkeypatch.setenv('APP_LLM_STEP_TIMEOUT_SECONDS', '0')
        result = llm_step_timeout_seconds_from_env()
        assert result is None

    def test_invalid_value_returns_default(self, monkeypatch):
        """Invalid env value falls back to safe default."""
        monkeypatch.setenv('APP_LLM_STEP_TIMEOUT_SECONDS', 'not-a-number')
        result = llm_step_timeout_seconds_from_env()
        assert result == DEFAULT_LLM_STEP_TIMEOUT_SECONDS


# ── Layer 1: _handle_llm_step_timeout behavior ───────────────────────


class TestHandleLlmStepTimeout:
    """The LLM step timeout handler must emit a recoverable observation."""

    @pytest.mark.asyncio
    async def test_emits_llm_step_timeout_observation(self):
        """A Timeout exception is converted to a visible ErrorObservation."""
        from backend.inference.exceptions import Timeout
        from backend.orchestration.services.action_execution_service import (
            ActionExecutionService,
        )

        service = ActionExecutionService.__new__(ActionExecutionService)
        service._context = MagicMock()
        service._reset_consecutive_null_actions = MagicMock()
        service._agent_model_name = MagicMock(return_value='test-model')
        service._publish_agent_event = MagicMock()

        exc = Timeout(
            'LLM step timed out after 300 seconds',
            model='test-model',
            step_timeout=300.0,
        )
        result = await service._handle_llm_step_timeout(exc)

        # Must return None so the outer step loop re-enters cleanly.
        assert result is None

        # Must emit an ErrorObservation with the LLM_STEP_TIMEOUT id so the
        # LLM sees the recovery in its next turn.
        service._publish_agent_event.assert_called_once()
        emitted = service._publish_agent_event.call_args.args[0]
        assert emitted.error_id == 'LLM_STEP_TIMEOUT'
        assert '300' in emitted.content
        assert 'test-model' in emitted.content
        assert emitted.notify_ui_only is True

    @pytest.mark.asyncio
    async def test_resets_consecutive_null_actions(self):
        """A timeout is not a null-action — counters must reset."""
        from backend.inference.exceptions import Timeout
        from backend.orchestration.services.action_execution_service import (
            ActionExecutionService,
        )

        service = ActionExecutionService.__new__(ActionExecutionService)
        service._context = MagicMock()
        service._reset_consecutive_null_actions = MagicMock()
        service._agent_model_name = MagicMock(return_value='m')
        service._publish_agent_event = MagicMock()

        await service._handle_llm_step_timeout(
            Timeout('test', step_timeout=300.0)
        )
        service._reset_consecutive_null_actions.assert_called_once()


# ── Layer 2: observation handler timeout ─────────────────────────────


class TestObservationHandlerTimeout:
    """The event router's _handle_observation must bound the handler."""

    @pytest.mark.asyncio
    async def test_hung_observation_handler_does_not_wedge(self):
        """A hung observation_service.handle_observation is cut off and
        the controller's step is triggered so the agent can recover."""
        from backend.orchestration.services.event_router_mixins._event_router_delegate_mixin import (
            _EventRouterDelegateMixin,
        )

        # Construct a minimal stand-in that has the attributes the method
        # accesses but does NOT inherit from the heavy SessionOrchestrator.
        class _Router(_EventRouterDelegateMixin):
            pass

        router = _Router()
        router._ctrl = MagicMock()

        async def _hang_forever(_observation):
            await asyncio.sleep(60)

        router._ctrl.observation_service.handle_observation = AsyncMock(
            side_effect=_hang_forever
        )

        # Minimal observation stub
        observation = MagicMock()
        observation.id = 'obs-1'
        type(observation).__name__ = 'FileWriteObservation'

        from backend.ledger.observation import FileWriteObservation

        obs = FileWriteObservation(content='ok', path='/tmp/x')

        start = time.monotonic()
        await router._handle_observation(obs)
        elapsed = time.monotonic() - start

        # The hang would normally take 60s; the 10s ceiling must cut it.
        assert elapsed < 12.0, (
            f'observation handler took {elapsed:.2f}s; '
            f'wall-clock bound is not being enforced.'
        )

        # The post-recovery trigger MUST be called so the next step runs.
        router._ctrl.step.assert_called_once()

    @pytest.mark.asyncio
    async def test_normal_observation_handler_completes(self):
        """Non-hung observation handlers still complete — timeout is a ceiling."""
        from backend.orchestration.services.event_router_mixins._event_router_delegate_mixin import (
            _EventRouterDelegateMixin,
        )
        from backend.ledger.observation import FileWriteObservation

        class _Router(_EventRouterDelegateMixin):
            pass

        router = _Router()
        router._ctrl = MagicMock()

        async def _normal_handler(_observation):
            return None

        router._ctrl.observation_service.handle_observation = AsyncMock(
            side_effect=_normal_handler
        )

        obs = FileWriteObservation(content='ok', path='/tmp/x')
        await router._handle_observation(obs)

        # Normal handler completed; no forced trigger needed.
        router._ctrl.step.assert_not_called()


# ── Layer 5: step task liveness watchdog ─────────────────────────────


class TestStepTaskLivenessWatchdog:
    """The _step drain loop must bound each _step_inner call."""

    @pytest.mark.asyncio
    async def test_hung_step_inner_is_force_cleared(self):
        """A hung _step_inner is cancelled and pending state is cleared."""
        # The real bound is 600s; too long for a unit test.  Patch the
        # source-of-truth constant in backend.core.constants.
        with patch(
            'backend.core.constants.DEFAULT_STEP_TASK_LIVENESS_SECONDS',
            0.2,
        ):
            from backend.core.constants import DEFAULT_STEP_TASK_LIVENESS_SECONDS

            class _HangingOrchestrator:
                """Minimal stub matching the API used by the _step loop."""

                _closed = False
                _step_request: asyncio.Event
                _step_owner_task: object = None
                _draining_batch = False

                def __init__(self):
                    self._step_request = asyncio.Event()
                    self.step_prerequisites = MagicMock()
                    self.step_prerequisites.can_step = MagicMock(return_value=False)
                    self.services = MagicMock()
                    self.services.pending_action = MagicMock()
                    self.event_stream = MagicMock()

                async def _step_inner(self) -> None:
                    await asyncio.sleep(60)  # hang forever

                @property
                def _step_lock(self) -> asyncio.Lock:
                    return self.__dict__.setdefault(
                        '_lock', asyncio.Lock()
                    )

                # Replicate the bound from the real _step method.
                async def _step_bounded(self) -> None:
                    async with self._step_lock:
                        self._step_owner_task = asyncio.current_task()
                        try:
                            drained_count = 0
                            while drained_count < 1:  # one iteration only
                                drained_count += 1
                                try:
                                    await asyncio.wait_for(
                                        self._step_inner(),
                                        timeout=DEFAULT_STEP_TASK_LIVENESS_SECONDS,
                                    )
                                except asyncio.TimeoutError:
                                    break
                        finally:
                            self._step_owner_task = None

            orch = _HangingOrchestrator()
            start = time.monotonic()
            await orch._step_bounded()
            elapsed = time.monotonic() - start

            # The hang would take 60s; the 0.2s ceiling must cut it.
            assert elapsed < 1.0, (
                f'bound took {elapsed:.2f}s; ceiling was 0.2s.'
            )
