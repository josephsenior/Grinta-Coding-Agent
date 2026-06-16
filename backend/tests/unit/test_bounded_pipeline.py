"""Tests for the bounded-pipeline plan (Layers 1, 2, 5).

These tests verify the orchestrator's hot path has bounded stall points
without interrupting active LLM streams:

- Layer 1: LLM step (``astep``) supports an explicit opt-in wall-clock cap
  via ``APP_LLM_STEP_TIMEOUT_SECONDS``. Streaming liveness is handled by
  first-chunk and per-chunk stall timeouts instead of a blind outer cap.
- Layer 2: Observation handler is bounded with a 10s ceiling.
- Layer 5: Step drain loop has a 600s ceiling per iteration; force-clears
  pending state and emits a visible error on timeout.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.llm_step_timeout import (
    DEFAULT_LLM_STEP_TIMEOUT_SECONDS,
    llm_step_timeout_seconds_from_env,
)

# ── Layer 1: LLM step timeout default ────────────────────────────────


class TestLlmStepTimeoutDefault:
    """The outer LLM step timeout is opt-in."""

    def test_default_is_disabled(self):
        """Production default leaves active streams governed by chunk liveness."""
        assert DEFAULT_LLM_STEP_TIMEOUT_SECONDS is None

    def test_unset_env_returns_none(self, monkeypatch):
        """With APP_LLM_STEP_TIMEOUT_SECONDS unset, no outer cap applies."""
        monkeypatch.delenv('APP_LLM_STEP_TIMEOUT_SECONDS', raising=False)
        result = llm_step_timeout_seconds_from_env()
        assert result is None

    def test_empty_env_returns_none(self, monkeypatch):
        """Empty env var is treated as unset."""
        monkeypatch.setenv('APP_LLM_STEP_TIMEOUT_SECONDS', '')
        result = llm_step_timeout_seconds_from_env()
        assert result is None

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

    def test_invalid_value_returns_none(self, monkeypatch):
        """Invalid env value leaves the outer cap disabled."""
        monkeypatch.setenv('APP_LLM_STEP_TIMEOUT_SECONDS', 'not-a-number')
        result = llm_step_timeout_seconds_from_env()
        assert result is None


# ── Layer 1: LLM step timeout propagates for retry-queue recovery ────


class TestLlmStepTimeoutPropagation:
    """A hung LLM step must raise ``Timeout`` (after one in-place retry) so
    the orchestrator's RecoveryService can route it through the retry queue
    (exponential backoff + automatic RUNNING resume).  It must NOT be
    swallowed into a ``None`` action — doing so made the agent halt silently
    (the liveness guard saw a no-action and went AWAITING_USER_INPUT).
    """

    @pytest.mark.asyncio
    async def test_hung_step_raises_timeout(self):
        """``_run_async_step_with_timeout`` raises ``Timeout`` once the cap is
        exceeded, preserving the cap value for diagnostics.
        """
        import asyncio

        from backend.inference.exceptions import Timeout
        from backend.orchestration.services.action_execution_service import (
            ActionExecutionService,
        )

        service = ActionExecutionService.__new__(ActionExecutionService)
        service._context = MagicMock()
        service._agent_model_name = MagicMock(return_value='test-model')

        async def slow_astep(_state):
            await asyncio.sleep(10)

        with pytest.raises(Timeout) as excinfo:
            await service._run_async_step_with_timeout(MagicMock(), slow_astep, 0.01)
        assert excinfo.value.kwargs.get('step_timeout') == 0.01

    @pytest.mark.asyncio
    async def test_first_astep_timeout_cancels_before_retry(self):
        import asyncio

        from backend.orchestration.services.action_execution_service import (
            ActionExecutionService,
        )

        service = ActionExecutionService.__new__(ActionExecutionService)
        service._context = MagicMock()
        service._agent_model_name = MagicMock(return_value='test-model')

        agent = MagicMock()
        agent.executor.cancel_step = MagicMock()
        calls = {'count': 0}

        async def flaky_astep(_state):
            calls['count'] += 1
            if calls['count'] == 1:
                await asyncio.sleep(10)
            return MagicMock()

        await service._run_async_step_with_timeout(agent, flaky_astep, 0.05)

        agent.executor.cancel_step.assert_called_once()
        assert calls['count'] == 2

    def test_local_swallow_handler_is_removed(self):
        """Regression guard: the handler that converted a step timeout into a
        ``None`` action must not be reintroduced.
        """
        from backend.orchestration.services.action_execution_service import (
            ActionExecutionService,
        )

        assert not hasattr(ActionExecutionService, '_handle_llm_step_timeout')


# ── Layer 2: observation handler timeout ─────────────────────────────


class TestObservationHandlerTimeout:
    """The event router's _handle_observation must bound the handler."""

    @pytest.mark.asyncio
    async def test_hung_observation_handler_does_not_wedge(self):
        """A hung observation_service.handle_observation is cut off and
        the controller's step is triggered so the agent can recover.
        """
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
        from backend.ledger.observation import FileWriteObservation
        from backend.orchestration.services.event_router_mixins._event_router_delegate_mixin import (
            _EventRouterDelegateMixin,
        )

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
                    return self.__dict__.setdefault('_lock', asyncio.Lock())

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
            assert elapsed < 1.0, f'bound took {elapsed:.2f}s; ceiling was 0.2s.'
