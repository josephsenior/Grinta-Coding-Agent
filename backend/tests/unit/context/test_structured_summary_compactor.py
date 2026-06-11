"""Tests for backend.context.compactor.strategies.structured_summary_compactor."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.context.compactor.compactor import Compaction
from backend.context.compactor.strategies.structured_summary_compactor import (
    StateSummary,
    StructuredSummaryCompactor,
)
from backend.ledger.action import MessageAction
from backend.ledger.event import Event, EventSource
from backend.ledger.observation.agent import AgentCondensationObservation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(eid: int, content: str = 'event content') -> Event:
    e = MessageAction(content=content, wait_for_response=False)
    e._source = EventSource.AGENT  # type: ignore[attr-defined]
    e.id = eid
    return e


def _summary_event(
    eid: int, message: str = 'previous summary'
) -> AgentCondensationObservation:
    e = AgentCondensationObservation(message)
    e.id = eid
    return e


def _make_llm(function_calling: bool = True) -> MagicMock:
    llm = MagicMock()
    llm.is_function_calling_active.return_value = function_calling
    llm.format_messages_for_llm.side_effect = lambda msgs: msgs
    return llm


def _make_tool_call_response(args: dict) -> MagicMock:
    """Build a mock LLM response with a single create_state_summary tool call."""
    tool_call = SimpleNamespace(
        function=SimpleNamespace(
            name='create_state_summary',
            arguments=json.dumps(args),
        )
    )
    message = SimpleNamespace(tool_calls=[tool_call])
    choice = SimpleNamespace(message=message)
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_view(events: list[Event]) -> MagicMock:
    """Minimal View mock that supports slicing and len."""
    view = MagicMock()
    view.events = events
    view.unhandled_condensation_request = False
    view.__len__ = MagicMock(return_value=len(events))
    view.__iter__ = MagicMock(return_value=iter(events))
    view.__getitem__ = MagicMock(side_effect=events.__getitem__)
    return view


# ---------------------------------------------------------------------------
# StateSummary
# ---------------------------------------------------------------------------


class TestStateSummary:
    def test_tool_description_has_required_fields(self):
        desc = StateSummary.tool_description()
        params = desc['function']['parameters']
        assert 'original_objective' in params['required']
        assert 'user_context' in params['required']
        assert 'completed_tasks' in params['required']
        assert 'pending_tasks' in params['required']

    def test_tool_description_includes_all_fields(self):
        desc = StateSummary.tool_description()
        props = desc['function']['parameters']['properties']
        for field_name in StateSummary.model_fields:
            assert field_name in props

    def test_str_includes_sections(self):
        s = StateSummary(
            user_context='Fix auth bug',
            completed_tasks='Updated token validation',
            pending_tasks='Write tests',
        )
        rendered = str(s)
        assert 'Fix auth bug' in rendered
        assert 'Updated token validation' in rendered
        assert 'Write tests' in rendered

    def test_empty_summary_does_not_raise(self):
        s = StateSummary()
        assert str(s) != ''

    def test_canonical_patch_prefers_explicit_patch_fields(self):
        s = StateSummary(
            pending_tasks='old pending task',
            current_working_step='old next step',
            files_modified='old.py',
            canonical_active_plan='patch plan',
            canonical_next_action='run focused test',
            canonical_active_files='backend/context/canonical_state.py',
            canonical_blockers='pytest still failing',
            narrative_summary='short current summary',
        )

        patch = s.canonical_patch()

        assert patch['active_plan'] == 'patch plan'
        assert patch['next_action'] == 'run focused test'
        assert patch['active_files'] == 'backend/context/canonical_state.py'
        assert patch['blockers'] == 'pytest still failing'
        assert patch['narrative_summary'] == 'short current summary'


# ---------------------------------------------------------------------------
# StructuredSummaryCondenser._validate_llm
# ---------------------------------------------------------------------------


class TestValidateLlm:
    def test_raises_when_function_calling_not_active(self):
        llm = _make_llm(function_calling=False)
        with pytest.raises(ValueError, match='function calling'):
            StructuredSummaryCompactor(llm=llm, max_size=100, keep_first=2)

    def test_does_not_raise_when_function_calling_active(self):
        llm = _make_llm(function_calling=True)
        # Should not raise
        condenser = StructuredSummaryCompactor(llm=llm, max_size=100, keep_first=2)
        assert condenser.llm is llm

    def test_does_not_raise_when_llm_is_none(self):
        # None LLM skips validation (used in test setup without real LLM)
        condenser = StructuredSummaryCompactor(llm=None, max_size=100, keep_first=2)
        assert condenser.llm is None


# ---------------------------------------------------------------------------
# StructuredSummaryCondenser._parse_llm_response
# ---------------------------------------------------------------------------


class TestParseLlmResponse:
    def setup_method(self):
        self.condenser = StructuredSummaryCompactor(
            llm=None, max_size=100, keep_first=2
        )

    def test_happy_path_returns_state_summary(self):
        args = {
            'user_context': 'Fix auth',
            'completed_tasks': 'Token validation updated',
            'pending_tasks': 'Add tests',
        }
        response = _make_tool_call_response(args)
        result = self.condenser._parse_llm_response(response)
        assert isinstance(result, StateSummary)
        assert result.user_context == 'Fix auth'
        assert result.completed_tasks == 'Token validation updated'

    def test_all_fields_round_trip(self):
        args = {
            'user_context': 'ctx',
            'completed_tasks': 'done',
            'pending_tasks': 'todo',
            'files_modified': 'auth.py',
            'tests_passing': 'true',
            'branch_name': 'fix-auth',
            'pr_status': 'open',
        }
        response = _make_tool_call_response(args)
        result = self.condenser._parse_llm_response(response)
        assert result.files_modified == 'auth.py'
        assert result.branch_name == 'fix-auth'
        assert result.pr_status == 'open'

    def test_empty_choices_falls_back_to_empty_summary(self):
        response = MagicMock()
        response.choices = []
        result = self.condenser._parse_llm_response(response)
        assert isinstance(result, StateSummary)
        assert result.user_context == ''

    def test_no_tool_calls_falls_back_to_empty_summary(self):
        message = SimpleNamespace(tool_calls=None)
        choice = SimpleNamespace(message=message)
        response = MagicMock()
        response.choices = [choice]
        result = self.condenser._parse_llm_response(response)
        assert isinstance(result, StateSummary)

    def test_wrong_tool_name_falls_back_to_empty_summary(self):
        tool_call = SimpleNamespace(
            function=SimpleNamespace(name='wrong_tool', arguments='{}')
        )
        message = SimpleNamespace(tool_calls=[tool_call])
        choice = SimpleNamespace(message=message)
        response = MagicMock()
        response.choices = [choice]
        result = self.condenser._parse_llm_response(response)
        assert isinstance(result, StateSummary)

    def test_invalid_json_falls_back_to_empty_summary(self):
        tool_call = SimpleNamespace(
            function=SimpleNamespace(name='create_state_summary', arguments='NOT JSON')
        )
        message = SimpleNamespace(tool_calls=[tool_call])
        choice = SimpleNamespace(message=message)
        response = MagicMock()
        response.choices = [choice]
        result = self.condenser._parse_llm_response(response)
        assert isinstance(result, StateSummary)


# ---------------------------------------------------------------------------
# StructuredSummaryCompactor.get_compaction
# ---------------------------------------------------------------------------


class TestGetCompaction:
    def test_prepare_view_sections_handles_empty_tail(self):
        condenser = StructuredSummaryCompactor(llm=None, max_size=4, keep_first=1)
        events = [_event(0), _event(1)]
        view = _make_view(events)

        _head, pruned_events, _summary_event = condenser._prepare_view_sections(view)

        assert pruned_events == [events[1]]

    async def test_returns_compaction_with_correct_events_dropped(self):
        """Events between keep_first and tail should be dropped; summary replaces them."""
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(llm=llm, max_size=10, keep_first=2)

        # 8 normal events, no existing summary
        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        response = _make_tool_call_response(
            {
                'user_context': 'fix bug',
                'completed_tasks': 'patched fn',
                'pending_tasks': 'tests',
            }
        )
        llm.acompletion = AsyncMock(return_value=response)

        with patch.object(condenser, '_add_response_metadata'):
            result = await condenser.get_compaction(view)

        assert isinstance(result, Compaction)
        assert result.action.pruned_events_start_id is not None
        assert result.action.pruned_events_end_id is not None
        assert condenser.last_state_patch['active_plan'] == 'tests'

    async def test_llm_receives_previous_summary_in_prompt(self):
        """When a summary event exists at keep_first, it is passed to the LLM."""
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(llm=llm, max_size=10, keep_first=2)

        events: list[Event] = [
            _event(0),
            _event(1),
            _summary_event(2, message='I remember everything'),
            _event(3),
            _event(4),
            _event(5),
        ]
        view = _make_view(events)

        response = _make_tool_call_response(
            {
                'user_context': 'ctx',
                'completed_tasks': 'done',
                'pending_tasks': 'todo',
            }
        )
        llm.acompletion = AsyncMock(return_value=response)

        with patch.object(condenser, '_add_response_metadata'):
            await condenser.get_compaction(view)

        # The prompt passed to the LLM should contain the previous summary text
        call_kwargs = llm.acompletion.call_args
        messages = call_kwargs[1]['messages'] if call_kwargs[1] else call_kwargs[0][0]
        prompt_text = str(messages)
        assert 'I remember everything' in prompt_text
