"""Tests for backend.context.compactor.strategies.structured_summary_compactor."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.context.compactor.compactor import Compaction
from backend.context.compactor.strategies.structured_summary_compactor import (
    DEFAULT_MIN_PROSE_LENGTH,
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


def _make_llm() -> MagicMock:
    """LLM mock — no function-calling requirement for prose compaction."""
    llm = MagicMock()
    llm.is_function_calling_active.return_value = True
    llm.format_messages_for_llm.side_effect = lambda msgs: msgs
    return llm


def _make_prose_response(content: str) -> MagicMock:
    """Build a mock LLM response whose choice message content is ``content``."""
    message = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(message=message)
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_list_content_response(blocks: list) -> MagicMock:
    """Build a mock LLM response whose message content is a list of blocks."""
    message = SimpleNamespace(content=blocks, tool_calls=None)
    choice = SimpleNamespace(message=message)
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_empty_choices_response() -> MagicMock:
    response = MagicMock()
    response.choices = []
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


def _long_prose(seed: str = 'Built the auth module from scratch') -> str:
    """Prose long enough to pass the default sanity gate."""
    return (seed + '. ') * (DEFAULT_MIN_PROSE_LENGTH // len(seed + '. ') + 1)


# ---------------------------------------------------------------------------
# _validate_llm / construction
# ---------------------------------------------------------------------------


class TestValidateLlm:
    def test_does_not_require_function_calling(self):
        llm = MagicMock()
        llm.is_function_calling_active.return_value = False
        llm.format_messages_for_llm.side_effect = lambda msgs: msgs
        # Must NOT raise: prose compaction uses plain completion.
        condenser = StructuredSummaryCompactor(llm=llm, max_size=100, keep_first=2)
        assert condenser.llm is llm

    def test_accepts_none_llm(self):
        condenser = StructuredSummaryCompactor(llm=None, max_size=100, keep_first=2)
        assert condenser.llm is None

    def test_prose_config_defaults(self):
        condenser = StructuredSummaryCompactor(llm=None, max_size=100, keep_first=2)
        assert condenser.min_prose_length == DEFAULT_MIN_PROSE_LENGTH
        assert condenser.max_repair_attempts == 2

    def test_prose_config_overrides(self):
        condenser = StructuredSummaryCompactor(
            llm=None,
            max_size=100,
            keep_first=2,
            min_prose_length=120,
            max_repair_attempts=2,
        )
        assert condenser.min_prose_length == 120
        assert condenser.max_repair_attempts == 2


# ---------------------------------------------------------------------------
# _passes_prose_sanity_gate
# ---------------------------------------------------------------------------


class TestProseSanityGate:
    def setup_method(self):
        self.condenser = StructuredSummaryCompactor(
            llm=None, max_size=100, keep_first=2, min_prose_length=50
        )

    def test_empty_fails(self):
        assert not self.condenser._passes_prose_sanity_gate('')

    def test_whitespace_only_fails(self):
        assert not self.condenser._passes_prose_sanity_gate('   \n\t  ')

    def test_short_fails(self):
        assert not self.condenser._passes_prose_sanity_gate('short summary')

    def test_long_passes(self):
        prose = 'x' * 60
        assert self.condenser._passes_prose_sanity_gate(prose)

    def test_boundary_length_passes(self):
        prose = 'x' * 50
        assert self.condenser._passes_prose_sanity_gate(prose)

    def test_just_below_boundary_fails(self):
        prose = 'x' * 49
        assert not self.condenser._passes_prose_sanity_gate(prose)


# ---------------------------------------------------------------------------
# _extract_prose_content
# ---------------------------------------------------------------------------


class TestExtractProseContent:
    def setup_method(self):
        self.condenser = StructuredSummaryCompactor(
            llm=None, max_size=100, keep_first=2
        )

    def test_string_content(self):
        response = _make_prose_response('hello prose')
        assert self.condenser._extract_prose_content(response) == 'hello prose'

    def test_list_of_strings(self):
        response = _make_list_content_response(['part one', 'part two'])
        assert self.condenser._extract_prose_content(response) == 'part one\npart two'

    def test_list_of_text_blocks(self):
        block = SimpleNamespace(text='block text')
        response = _make_list_content_response([block])
        assert self.condenser._extract_prose_content(response) == 'block text'

    def test_empty_choices_returns_empty(self):
        response = _make_empty_choices_response()
        assert self.condenser._extract_prose_content(response) == ''

    def test_missing_content_returns_empty(self):
        message = SimpleNamespace(content=None, tool_calls=None)
        choice = SimpleNamespace(message=message)
        response = MagicMock()
        response.choices = [choice]
        assert self.condenser._extract_prose_content(response) == ''


# ---------------------------------------------------------------------------
# get_compaction — prose path
# ---------------------------------------------------------------------------


class TestGetCompaction:
    async def test_prose_summary_accepted_when_long_enough(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(llm=llm, max_size=10, keep_first=2)

        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        prose = _long_prose('Built the auth module')
        llm.acompletion = AsyncMock(return_value=_make_prose_response(prose))

        with patch.object(condenser, '_add_response_metadata'):
            result = await condenser.get_compaction(view)

        assert isinstance(result, Compaction)
        assert result.action.summary.strip() == prose.strip()

    async def test_short_prose_accepted_after_retries(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(llm=llm, max_size=10, keep_first=2)

        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        llm.acompletion = AsyncMock(return_value=_make_prose_response('too short'))

        with patch.object(condenser, '_add_response_metadata'):
            result = await condenser.get_compaction(view)

        assert isinstance(result, Compaction)
        assert result.action.summary == 'too short'

    async def test_empty_prose_raises(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(llm=llm, max_size=10, keep_first=2)

        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        llm.acompletion = AsyncMock(return_value=_make_prose_response(''))

        with patch.object(condenser, '_add_response_metadata'):
            with pytest.raises(RuntimeError, match='empty summary'):
                await condenser.get_compaction(view)

    async def test_llm_exception_propagates(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(llm=llm, max_size=10, keep_first=2)

        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        llm.acompletion = AsyncMock(side_effect=RuntimeError('provider down'))

        with patch.object(condenser, '_add_response_metadata'):
            with pytest.raises(RuntimeError, match='provider down'):
                await condenser.get_compaction(view)

    async def test_retry_recovers_after_short_first_attempt(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(
            llm=llm,
            max_size=10,
            keep_first=2,
            min_prose_length=50,
            max_repair_attempts=1,
        )

        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        good_prose = 'x' * 200
        llm.acompletion = AsyncMock(
            side_effect=[
                _make_prose_response('short'),
                _make_prose_response(good_prose),
            ]
        )

        with patch.object(condenser, '_add_response_metadata'):
            result = await condenser.get_compaction(view)

        assert result.action.summary == good_prose
        assert llm.acompletion.await_count == 2

    async def test_retries_by_default_on_short_output(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(llm=llm, max_size=10, keep_first=2)

        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        llm.acompletion = AsyncMock(
            side_effect=[
                _make_prose_response('short'),
                _make_prose_response(_long_prose()),
            ]
        )

        with patch.object(condenser, '_add_response_metadata'):
            await condenser.get_compaction(view)

        assert llm.acompletion.await_count == 2

    async def test_accepts_short_output_after_retries_exhausted(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(
            llm=llm, max_size=10, keep_first=2, max_repair_attempts=1
        )

        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        llm.acompletion = AsyncMock(return_value=_make_prose_response('short'))

        with patch.object(condenser, '_add_response_metadata'):
            result = await condenser.get_compaction(view)

        assert llm.acompletion.await_count == 2
        assert result.action.summary == 'short'

    async def test_streamed_prose_is_extracted_from_accumulated_text(self):
        """The TUI stream and committed summary must share the same accumulated text."""
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(
            llm=llm,
            max_size=10,
            keep_first=2,
            min_prose_length=50,
        )
        events = [_event(i) for i in range(8)]
        view = _make_view(events)
        good_prose = '## USER GOAL\n' + ('detail ' * 40)

        async def _astream(messages):
            yield {
                'choices': [{'delta': {'content': good_prose}, 'finish_reason': None}]
            }
            yield {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}

        llm.astream = _astream
        llm.acompletion = AsyncMock()
        emitted: list[str] = []
        condenser.streaming_emitter = lambda _chunk, accumulated, _final: (
            emitted.append(accumulated)
        )

        with patch.object(condenser, '_add_response_metadata'):
            result = await condenser.get_compaction(view)

        assert result.action.summary == good_prose.strip()
        llm.acompletion.assert_not_awaited()
        assert good_prose in emitted[-1]

    async def test_streamed_reasoning_content_excluded_from_prose(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(
            llm=llm,
            max_size=10,
            keep_first=2,
            min_prose_length=50,
        )
        events = [_event(i) for i in range(8)]
        view = _make_view(events)
        good_prose = '## USER GOAL\n' + ('x' * 120)
        reasoning = 'internal thinking ' * 40

        async def _astream(messages):
            yield {
                'choices': [
                    {
                        'delta': {'reasoning_content': reasoning},
                        'finish_reason': None,
                    }
                ]
            }
            yield {
                'choices': [{'delta': {'content': good_prose}, 'finish_reason': None}]
            }

        llm.astream = _astream
        llm.acompletion = AsyncMock()
        emitted: list[str] = []
        condenser.streaming_emitter = lambda _chunk, accumulated, _final: (
            emitted.append(accumulated)
        )

        with patch.object(condenser, '_add_response_metadata'):
            result = await condenser.get_compaction(view)

        assert good_prose in result.action.summary
        assert reasoning.strip() not in result.action.summary
        assert emitted
        assert reasoning.strip() not in emitted[-1]

    async def test_llm_receives_previous_summary_in_prompt(self):
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

        llm.acompletion = AsyncMock(return_value=_make_prose_response(_long_prose()))

        with patch.object(condenser, '_add_response_metadata'):
            await condenser.get_compaction(view)

        call_args = llm.acompletion.call_args
        messages = call_args.kwargs.get('messages') or call_args.args[0]
        prompt_text = str(messages)
        assert 'I remember everything' in prompt_text

    async def test_no_tools_passed_to_llm(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(llm=llm, max_size=10, keep_first=2)

        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        llm.acompletion = AsyncMock(return_value=_make_prose_response(_long_prose()))

        with patch.object(condenser, '_add_response_metadata'):
            await condenser.get_compaction(view)

        call_kwargs = llm.acompletion.call_args.kwargs
        assert 'tools' not in call_kwargs
        assert 'tool_choice' not in call_kwargs
        assert 'response_format' not in call_kwargs

    def test_prepare_view_sections_handles_empty_tail(self):
        condenser = StructuredSummaryCompactor(llm=None, max_size=4, keep_first=1)
        events = [_event(0), _event(1)]
        view = _make_view(events)

        _head, pruned_events, _summary_event = condenser._prepare_view_sections(view)

        assert pruned_events == [events[1]]


# ---------------------------------------------------------------------------
# _build_condensation_prompt
# ---------------------------------------------------------------------------


class TestBuildCondensationPrompt:
    def setup_method(self):
        self.condenser = StructuredSummaryCompactor(
            llm=None, max_size=100, keep_first=2
        )

    def _build_prompt(self, summary_text: str = 'previous summary') -> str:
        summary_event = _summary_event(0, message=summary_text)
        return self.condenser._build_condensation_prompt(summary_event, [])

    def test_prompt_contains_previous_summary_section(self):
        prompt = self._build_prompt()
        assert '<PREVIOUS_WORKING_MEMORY>' in prompt
        assert '</PREVIOUS_WORKING_MEMORY>' in prompt

    def test_prompt_includes_previous_summary_content(self):
        prompt = self._build_prompt(summary_text='Built X from scratch')
        assert 'Built X from scratch' in prompt

    def test_prompt_treats_previous_memory_as_revisable(self):
        prompt = self._build_prompt()
        assert 'may be stale or mistaken' in prompt.lower()
        assert 'later direct evidence wins' in prompt.lower()

    def test_prompt_frames_compaction_as_agent_continuity(self):
        prompt = self._build_prompt()
        assert 'same agent model' in prompt.lower()
        assert 'continuity of your own reasoning' in prompt.lower()

    def test_prompt_includes_chronological_evidence_section(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [_event(1)]
        )
        assert '<CHRONOLOGICAL_EVIDENCE>' in prompt
        assert '</CHRONOLOGICAL_EVIDENCE>' in prompt

    def test_prompt_reasserts_summary_instruction_after_long_evidence(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0),
            [_event(1, content='assistant text <tool_call>replace_string</tool_call>')],
        )

        evidence_end = prompt.index('</CHRONOLOGICAL_EVIDENCE>')
        final_directive = prompt.index('<FINAL_SUMMARY_DIRECTIVE>')
        assert final_directive > evidence_end
        tail = prompt[final_directive:]
        assert 'quoted source material, not a conversation to continue' in tail
        assert 'Do not continue the final agent message' in tail
        assert 'imitate its tool-call syntax' in tail
        assert 'output only the reconciled working-memory summary' in tail

    def test_prompt_includes_raw_event_identity(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [_event(1)]
        )
        assert '<EVENT id="1"' in prompt

    def test_prompt_includes_full_ordered_evidence_not_a_heuristic_tail(self):
        events = [_event(i, content=f'event {i}') for i in range(20)]
        prompt = self.condenser._build_condensation_prompt(_summary_event(0), events)
        evidence = prompt[prompt.index('<CHRONOLOGICAL_EVIDENCE>') :]
        assert 'event 0' in evidence
        assert 'event 19' in evidence
        assert evidence.index('event 0') < evidence.index('event 19')

    def test_prompt_includes_pruned_events(self):
        event = _event(42, content='Created autograd/tensor.py')
        prompt = self.condenser._build_condensation_prompt(_summary_event(0), [event])
        assert 'Created autograd/tensor.py' in prompt

    def test_prompt_leaves_task_specific_organization_to_model(self):
        prompt = self._build_prompt()
        assert 'Choose the organization that best fits the task' in prompt

    def test_prompt_has_budget_constraint(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [], char_limit=48000
        )
        assert '48000 characters' in prompt

    def test_prompt_budget_reflects_char_limit(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [], char_limit=12000
        )
        assert '12000 characters' in prompt

    def test_prompt_preserves_precise_task_evidence_without_fixed_categories(self):
        prompt = self._build_prompt()
        assert "user's current intent and constraints" in prompt
        assert 'exact identifiers, paths, commands' in prompt
        assert 'errors, and event references' in prompt

    def test_prompt_instructs_failed_approaches_when_useful(self):
        prompt = self._build_prompt()
        assert 'failed approaches worth avoiding' in prompt.lower()

    def test_prompt_requests_only_final_reconciled_memory(self):
        prompt = self._build_prompt()
        assert 'Output only the final reconciled working memory' in prompt

    def test_prompt_distinguishes_observation_from_inference(self):
        prompt = self._build_prompt()
        assert 'distinguish observation from inference' in prompt

    def test_prompt_preserves_user_completion_boundary_across_milestones(self):
        prompt = self._build_prompt()
        assert 'completion boundary exactly' in prompt
        assert 'completed subproblems as milestones' in prompt
        assert 'cannot fit in one session' in prompt
        assert 'preserve the next actionable step' in prompt

    def test_durable_task_state_is_read_only_input_not_summary_content(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0, '## USER GOAL\nStale duplicate objective'),
            [],
            durable_task_state_context=(
                '- Recorded overall objective: Build the complete compiler\n'
                '- Recorded overall status: ACTIVE'
            ),
        )

        assert '<DURABLE_TASK_STATE>' in prompt
        assert 'Build the complete compiler' in prompt
        assert 'freshly injected into every subsequent agent prompt' in prompt
        assert 'Do not restate, summarize, revise' in prompt
        assert 'omit the duplicate from the new memory' in prompt
        assert 'without reproducing the durable task plan' in prompt

    def test_missing_durable_task_state_keeps_goal_as_fallback(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [], durable_task_state_context=''
        )

        assert '<DURABLE_TASK_STATE>' not in prompt
        assert 'No durable task state is available' in prompt
        assert 'Preserve the user objective' in prompt

    def test_legacy_prompt_omits_goal_output_when_task_state_is_durable(self):
        with patch.object(
            self.condenser,
            '_durable_task_state_context',
            return_value='- Recorded overall objective: Build everything',
        ):
            prompt = self.condenser._build_legacy_condensation_prompt(
                _summary_event(0, '## USER GOAL\nOld duplicate'), []
            )

        assert '<DURABLE_TASK_STATE>' in prompt
        assert 'Do not emit a ## USER GOAL section' in prompt
        assert 'PREVIOUS GOAL SYNTHESIS' not in prompt
        assert (
            'resume from this summary together with the separately injected' in prompt
        )
        assert prompt.rfind('<FINAL_SUMMARY_DIRECTIVE>') > prompt.rfind(
            '</RECENT RAW EVENTS>'
        )
        assert 'Do not reproduce <DURABLE_TASK_STATE>' in prompt


# ---------------------------------------------------------------------------
# _digest_events — event pre-digestion
# ---------------------------------------------------------------------------


class TestDigestEvents:
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
        from backend.core.enums import EventSource
        from backend.ledger.action.message import MessageAction

        user_event = MessageAction(content='Fix the auth bug')
        user_event.source = EventSource.USER
        user_event.id = 0
        agent_event = MessageAction(content='I will fix the auth bug')
        agent_event.source = EventSource.AGENT
        agent_event.id = 1
        result = self.condenser._digest_events([user_event, agent_event])
        # User messages are injected separately via USER MESSAGES section,
        # not in the event digest. Only agent reasoning should appear.
        assert 'User messages' not in result
        assert 'Fix the auth bug' not in result
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
# USER GOAL section / sourced triggers
# ---------------------------------------------------------------------------


class TestUserGoalSection:
    def setup_method(self):
        self.condenser = StructuredSummaryCompactor(
            llm=_make_llm(), max_size=100, keep_first=2
        )

    def test_prompt_includes_previous_goal_when_present(self):
        prev = _summary_event(0, '## USER GOAL\nBuild a compiler\n## OTHER\nstuff')
        prompt = self.condenser._build_condensation_prompt(prev, [], char_limit=48000)
        assert '<PREVIOUS_WORKING_MEMORY>' in prompt
        assert 'Build a compiler' in prompt

    def test_prompt_omits_previous_goal_when_absent(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [], char_limit=48000
        )
        assert 'PREVIOUS GOAL SYNTHESIS' not in prompt

    def test_previous_goal_not_truncated_by_char_limit(self):
        long_goal = 'A user wants X with ' + 'very specific constraints ' * 300
        prev = _summary_event(0, f'## USER GOAL\n{long_goal}\n## OTHER\nstuff')
        prompt = self.condenser._build_condensation_prompt(prev, [], char_limit=2000)
        assert long_goal[:200] in prompt

    def test_previous_goal_synthesis_injected_from_prior_summary(self):
        summary = (
            '## USER GOAL\nBuild a compiler with X constraints\n\n## UNRESOLVED\nNone'
        )
        summary_event = _summary_event(0, message=summary)
        prompt = self.condenser._build_condensation_prompt(
            summary_event, [], char_limit=48000
        )
        assert '<PREVIOUS_WORKING_MEMORY>' in prompt
        assert 'Build a compiler with X constraints' in prompt

    def test_previous_goal_synthesis_omitted_when_no_prior_goal(self):
        summary_event = _summary_event(0, message='## UNRESOLVED\nNone')
        prompt = self.condenser._build_condensation_prompt(
            summary_event, [], char_limit=48000
        )
        assert 'PREVIOUS GOAL SYNTHESIS' not in prompt

    def test_prompt_includes_user_intent_instruction(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [], char_limit=48000
        )
        assert "user's current intent and constraints" in prompt


# ---------------------------------------------------------------------------
# Length-regression tripwire
# ---------------------------------------------------------------------------


class TestGoalRegressionTripwire:
    def setup_method(self):
        self.condenser = StructuredSummaryCompactor(
            llm=_make_llm(), max_size=100, keep_first=2
        )

    def test_warns_when_goal_shrinks_significantly(self):
        previous = 'A' * 1000
        new_goal = '## USER GOAL\n' + 'B' * 100 + '\n\n## UNRESOLVED\nstuff'
        with patch(
            'backend.context.compactor.strategies.structured_summary_compactor.logger'
        ) as mock_logger:
            self.condenser._check_goal_regression(new_goal, previous)
        mock_logger.warning.assert_called_once()
        assert 'regressed' in mock_logger.warning.call_args[0][0]

    def test_no_warn_when_goal_grows(self):
        previous = 'A' * 100
        new_goal = '## USER GOAL\n' + 'B' * 500 + '\n\n## UNRESOLVED\nstuff'
        with patch(
            'backend.context.compactor.strategies.structured_summary_compactor.logger'
        ) as mock_logger:
            self.condenser._check_goal_regression(new_goal, previous)
        mock_logger.warning.assert_not_called()

    def test_no_warn_when_no_previous_goal(self):
        new_goal = '## USER GOAL\nBuild something\n\n## UNRESOLVED\nstuff'
        with patch(
            'backend.context.compactor.strategies.structured_summary_compactor.logger'
        ) as mock_logger:
            self.condenser._check_goal_regression(new_goal, None)
        mock_logger.warning.assert_not_called()

    def test_no_warn_when_goal_shrinks_slightly(self):
        previous = 'A' * 1000
        new_goal = '## USER GOAL\n' + 'B' * 700 + '\n\n## UNRESOLVED\nstuff'
        with patch(
            'backend.context.compactor.strategies.structured_summary_compactor.logger'
        ) as mock_logger:
            self.condenser._check_goal_regression(new_goal, previous)
        mock_logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# _extract_section helper
# ---------------------------------------------------------------------------


class TestExtractSection:
    def test_extracts_section_between_headers(self):
        text = '## USER GOAL\nBuild a compiler\n\n## UNRESOLVED\nNone'
        result = StructuredSummaryCompactor._extract_section(text, '## USER GOAL')
        assert 'Build a compiler' in result
        assert '## UNRESOLVED' not in result

    def test_extracts_last_section_to_end(self):
        text = '## DECISIONS\nUse fltk\nReason: fast'
        result = StructuredSummaryCompactor._extract_section(text, '## DECISIONS')
        assert 'Use fltk' in result
        assert 'Reason: fast' in result

    def test_returns_empty_when_header_not_found(self):
        text = '## UNRESOLVED\nNone'
        result = StructuredSummaryCompactor._extract_section(text, '## USER GOAL')
        assert result == ''
