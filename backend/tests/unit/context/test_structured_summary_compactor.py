"""Tests for backend.context.compactor.strategies.structured_summary_compactor."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.context.compactor.compactor import Compaction
from backend.context.compactor.strategies.structured_summary_compactor import (
    Dependency,
    FailedCommand,
    FileModification,
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

    def test_tool_description_uses_json_schema_for_nested_models(self):
        desc = StateSummary.tool_description()
        params = desc['function']['parameters']
        props = params['properties']
        # files_modified should be an array with $ref to FileModification
        files_schema = props['files_modified']
        assert files_schema['type'] == 'array'
        assert '$ref' in files_schema['items']
        # Definitions should be present
        assert 'definitions' in params
        assert 'FileModification' in params['definitions']
        fm_def = params['definitions']['FileModification']
        assert 'path' in fm_def['properties']
        assert 'change_type' in fm_def['properties']
        # error_messages should reference FailedCommand
        errors_schema = props['error_messages']
        assert errors_schema['type'] == 'array'
        assert '$ref' in errors_schema['items']
        assert 'FailedCommand' in params['definitions']
        # dependencies should reference Dependency
        deps_schema = props['dependencies']
        assert deps_schema['type'] == 'array'
        assert '$ref' in deps_schema['items']
        assert 'Dependency' in params['definitions']

    def test_str_renders_list_fields(self):
        s = StateSummary(
            files_modified=[FileModification(path='/a.py', change_type='created')],
            error_messages=[
                FailedCommand(command='pytest', exact_error='FAIL', exit_code=1),
            ],
            dependencies=[Dependency(name='fastapi', version='0.100')],
        )
        rendered = str(s)
        assert '/a.py' in rendered
        assert '(created)' in rendered
        assert 'exit=1' in rendered
        assert 'fastapi@0.100' in rendered

    def test_canonical_patch_prefers_explicit_patch_fields(self):
        s = StateSummary(
            pending_tasks='old pending task',
            files_modified=[FileModification(path='old.py', change_type='modified')],
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

    def test_canonical_patch_falls_back_to_files_modified(self):
        s = StateSummary(
            files_modified=[
                FileModification(path='/src/main.py', change_type='created'),
                FileModification(path='/src/util.py', change_type='modified'),
            ],
        )
        patch = s.canonical_patch()
        assert '/src/main.py' in patch['active_files']
        assert '/src/util.py' in patch['active_files']


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
            'files_modified': [
                {'path': '/abs/auth.py', 'change_type': 'modified'},
            ],
            'error_messages': [
                {'command': 'pytest', 'exact_error': 'AssertionError', 'exit_code': 1},
            ],
            'exact_commands_and_results': [
                {'command': 'npm test', 'exit_code': 0, 'output_summary': '5 passed'},
            ],
            'dependencies': [
                {'name': 'pydantic', 'version': '2.0'},
            ],
            'test_status': 'failing (test_auth, test_token)',
            'vcs_status': 'branch=fix-auth, commits=true, pr=open',
        }
        response = _make_tool_call_response(args)
        result = self.condenser._parse_llm_response(response)
        assert len(result.files_modified) == 1
        assert result.files_modified[0].path == '/abs/auth.py'
        assert result.files_modified[0].change_type == 'modified'
        assert len(result.error_messages) == 1
        assert result.error_messages[0].exit_code == 1
        assert len(result.exact_commands_and_results) == 1
        assert result.exact_commands_and_results[0].exit_code == 0
        assert len(result.dependencies) == 1
        assert result.dependencies[0].name == 'pydantic'
        assert result.test_status == 'failing (test_auth, test_token)'
        assert result.vcs_status == 'branch=fix-auth, commits=true, pr=open'

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

    def test_string_for_list_field_falls_back_to_empty_summary(self):
        """When LLM returns a string for a list field, validation fails gracefully."""
        args = {
            'user_context': 'ctx',
            'completed_tasks': 'done',
            'pending_tasks': 'todo',
            'files_modified': 'just a string',  # wrong type
        }
        response = _make_tool_call_response(args)
        result = self.condenser._parse_llm_response(response)
        # Falls back to empty summary
        assert isinstance(result, StateSummary)
        assert result.files_modified == []


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


# ---------------------------------------------------------------------------
# _build_condensation_prompt — NARRATIVE_SUMMARY instructions
# ---------------------------------------------------------------------------


class TestBuildCondensationPrompt:
    """Tests for the NARRATIVE_SUMMARY instructions in the compaction prompt."""

    def setup_method(self):
        self.condenser = StructuredSummaryCompactor(
            llm=None, max_size=100, keep_first=2
        )

    def _build_prompt(self, summary_text: str = 'previous summary') -> str:
        summary_event = _summary_event(0, message=summary_text)
        return self.condenser._build_condensation_prompt(summary_event, [])

    def test_prompt_contains_narrative_summary_section(self):
        prompt = self._build_prompt()
        assert 'NARRATIVE_SUMMARY' in prompt

    def test_prompt_instructs_full_session_arc(self):
        prompt = self._build_prompt()
        assert 'FULL session arc' in prompt

    def test_prompt_instructs_preserve_previous_summary(self):
        prompt = self._build_prompt()
        assert 'PREVIOUS SUMMARY' in prompt
        assert 'PRESERVE' in prompt

    def test_prompt_instructs_preserve_from_scratch_framing(self):
        prompt = self._build_prompt()
        assert 'from scratch' in prompt.lower() or 'Built from scratch' in prompt

    def test_prompt_gives_structure_example(self):
        prompt = self._build_prompt()
        assert 'Built' in prompt
        assert 'Remaining' in prompt

    def test_prompt_warns_against_replacing_with_recent_only(self):
        prompt = self._build_prompt()
        assert 'Do NOT replace' in prompt

    def test_prompt_includes_previous_summary_content(self):
        prompt = self._build_prompt(summary_text='Built X from scratch')
        assert 'Built X from scratch' in prompt

    def test_prompt_includes_pruned_events(self):
        event = _event(42, content='Created autograd/tensor.py')
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [event]
        )
        assert 'Created autograd/tensor.py' in prompt


# ---------------------------------------------------------------------------
# _digest_events — event pre-digestion
# ---------------------------------------------------------------------------


class TestDigestEvents:
    """Tests for the event digestion logic."""

    def setup_method(self):
        self.condenser = StructuredSummaryCompactor(
            llm=None, max_size=100, keep_first=2
        )

    def test_empty_events_returns_placeholder(self):
        result = self.condenser._digest_events([])
        assert result == '(no events)'

    def test_file_creations_grouped(self):
        from backend.ledger.action.files import FileEditAction
        events = [
            FileEditAction(path='src/a.py', command='create_file'),
            FileEditAction(path='src/b.py', command='create_file'),
            FileEditAction(path='src/c.py', command='create_file'),
        ]
        for i, e in enumerate(events):
            e.id = i
        result = self.condenser._digest_events(events)
        assert 'Files created (3)' in result
        assert 'src/a.py' in result
        assert 'src/b.py' in result
        assert 'src/c.py' in result

    def test_file_creations_truncated_at_15(self):
        from backend.ledger.action.files import FileEditAction
        events = [
            FileEditAction(path=f'src/file_{i}.py', command='create_file')
            for i in range(20)
        ]
        for i, e in enumerate(events):
            e.id = i
        result = self.condenser._digest_events(events)
        assert 'Files created (20)' in result
        assert '... and 5 more' in result

    def test_file_edits_deduplicated(self):
        from backend.ledger.action.files import FileEditAction
        events = [
            FileEditAction(path='src/a.py', command='replace_string'),
            FileEditAction(path='src/a.py', command='replace_string'),
            FileEditAction(path='src/a.py', command='replace_string'),
        ]
        for i, e in enumerate(events):
            e.id = i
        result = self.condenser._digest_events(events)
        assert 'Files edited (1 unique)' in result
        assert 'src/a.py' in result

    def test_commands_with_exit_codes(self):
        from backend.ledger.action.commands import CmdRunAction
        from backend.ledger.observation.commands import CmdOutputObservation
        events = [
            CmdRunAction(command='pytest'),
            CmdOutputObservation(content='5 passed', command='pytest'),
        ]
        for i, e in enumerate(events):
            e.id = i
        events[1].exit_code = 0
        result = self.condenser._digest_events(events)
        assert 'Commands run' in result
        assert 'pytest' in result
        assert 'exit=0' in result

    def test_failed_commands_appear_in_errors(self):
        from backend.ledger.action.commands import CmdRunAction
        from backend.ledger.observation.commands import CmdOutputObservation
        events = [
            CmdRunAction(command='npm test'),
            CmdOutputObservation(content='FAIL: test_auth', command='npm test'),
        ]
        for i, e in enumerate(events):
            e.id = i
        events[1].exit_code = 1
        result = self.condenser._digest_events(events)
        assert 'Errors (1)' in result
        assert 'npm test' in result
        assert 'exit=1' in result

    def test_user_messages_separated_from_agent(self):
        from backend.ledger.action.message import MessageAction
        from backend.core.enums import EventSource
        user_event = MessageAction(content='Fix the auth bug')
        user_event.source = EventSource.USER
        user_event.id = 0
        agent_event = MessageAction(content='I will fix the auth bug')
        agent_event.source = EventSource.AGENT
        agent_event.id = 1
        result = self.condenser._digest_events([user_event, agent_event])
        assert 'User messages (1)' in result
        assert 'Fix the auth bug' in result
        assert 'Agent reasoning' in result

    def test_condensation_events_skipped(self):
        from backend.ledger.observation.agent import AgentCondensationObservation
        events = [
            AgentCondensationObservation('old summary'),
            AgentCondensationObservation('older summary'),
        ]
        for i, e in enumerate(events):
            e.id = i
        result = self.condenser._digest_events(events)
        assert result == '(no events)'

    def test_code_navigation_grouped(self):
        from backend.ledger.action.search import FindSymbolsAction
        events = [
            FindSymbolsAction(query='AuthHandler'),
            FindSymbolsAction(query='TokenStore'),
        ]
        for i, e in enumerate(events):
            e.id = i
        result = self.condenser._digest_events(events)
        assert 'Code navigation' in result
        assert 'AuthHandler' in result
        assert 'TokenStore' in result


# ---------------------------------------------------------------------------
# _build_condensation_prompt — event digest integration
# ---------------------------------------------------------------------------


class TestBuildCondensationPromptWithDigest:
    """Tests that the prompt uses the event digest format."""

    def setup_method(self):
        self.condenser = StructuredSummaryCompactor(
            llm=None, max_size=100, keep_first=2
        )

    def test_prompt_contains_event_digest_section(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [_event(1)]
        )
        assert '<EVENT DIGEST>' in prompt
        assert '</EVENT DIGEST>' in prompt

    def test_prompt_contains_recent_raw_events_section(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [_event(1)]
        )
        assert '<RECENT RAW EVENTS' in prompt

    def test_prompt_only_includes_last_5_raw_events(self):
        events = [_event(i, content=f'event {i}') for i in range(20)]
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), events
        )
        raw_section = prompt[prompt.index('<RECENT RAW EVENTS'):]
        assert 'event 19' in raw_section
        assert 'event 15' in raw_section
        assert 'event 14' not in raw_section

    def test_prompt_mentions_test_and_vcs_field_guidance(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [_event(1)]
        )
        assert 'test_status' in prompt
        assert 'vcs_status' in prompt
