from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.engine.orchestrator import Orchestrator
from backend.ledger.action import MessageAction
from backend.ledger.action.empty import NullAction


class _Safety:
    def apply(self, response_text, actions):
        return True, actions


class _LLMStub:
    def __init__(self, response_content: str):
        self._response_content = response_content
        self.last_kwargs: dict | None = None

        # Provide a minimal features object
        self.features = SimpleNamespace(supports_stop_words=True)

    def is_function_calling_active(self) -> bool:
        return False

    def completion(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            id='r1',
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=self._response_content))
            ],
        )


def _make_result(content: str):
    """Build a minimal LLM-result stub with no actions."""
    return SimpleNamespace(
        actions=[],
        response=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content)
                )
            ]
        ),
        execution_time=0.0,
    )


def _make_orchestrator(tmp_path) -> Orchestrator:
    """Construct an Orchestrator with all heavy dependencies mocked out."""
    orch = object.__new__(Orchestrator)
    orch.llm = MagicMock()
    orch.planner = MagicMock()
    orch.executor = MagicMock()
    orch.tools = MagicMock()
    orch.memory_manager = MagicMock()
    orch.event_stream = MagicMock()
    orch.pending_actions = []
    orch.deferred_actions = []
    return orch


class TestBuildFallbackAction:
    """Integration-level tests for _build_fallback_action."""

    def test_empty_content_returns_null_action(self, tmp_path) -> None:
        orch = _make_orchestrator(tmp_path)
        obs = orch._build_fallback_action(_make_result(''))
        assert isinstance(obs, NullAction)

    def test_whitespace_only_returns_null_action(self, tmp_path) -> None:
        orch = _make_orchestrator(tmp_path)
        obs = orch._build_fallback_action(_make_result('   \n  '))
        assert isinstance(obs, NullAction)

    @pytest.mark.parametrize(
        'text',
        [
            # JSON planning blob — the exact pattern from the reported bug
            '{ "analysis": "env check", "plan": "1. python --version", "commands": [] }',
            # Plain narration
            'We need to build an expense sharing service.',
            # Model pretending it executed something
            'I have created the FastAPI application and configured SQLite.',
            # Genuine question — must still be non-blocking; model must use communicate_with_user
            'Which Python version should I target?',
        ],
    )
    def test_any_non_empty_text_does_not_pause_loop(self, text: str, tmp_path) -> None:
        orch = _make_orchestrator(tmp_path)
        action = orch._build_fallback_action(_make_result(text))
        assert isinstance(action, MessageAction)
        assert action.wait_for_response is False, (
            'Any text-only LLM response must continue the loop; '
            'use communicate_with_user to pause for real user input'
        )

    def test_no_choices_returns_null_action(self, tmp_path) -> None:
        orch = _make_orchestrator(tmp_path)
        result = SimpleNamespace(actions=[], response=None, execution_time=0.0)
        obs = orch._build_fallback_action(result)
        assert isinstance(obs, NullAction)

