"""Tests for backend.context.compactor.strategies.structured_summary_compactor."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
        assert result.action.summary == prose
        assert condenser.last_degraded is False

    async def test_short_prose_degrades_and_does_not_wipe(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(llm=llm, max_size=10, keep_first=2)

        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        llm.acompletion = AsyncMock(return_value=_make_prose_response('too short'))

        with patch.object(condenser, '_add_response_metadata'):
            result = await condenser.get_compaction(view)

        assert isinstance(result, Compaction)
        # Degraded flag set so the pipeline rejects this compaction.
        assert condenser.last_degraded is True
        # Summary is the degraded audit text, never an empty wipe.
        assert result.action.summary
        assert 'degraded' in result.action.summary

    async def test_empty_prose_degrades(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(llm=llm, max_size=10, keep_first=2)

        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        llm.acompletion = AsyncMock(return_value=_make_prose_response(''))

        with patch.object(condenser, '_add_response_metadata'):
            result = await condenser.get_compaction(view)

        assert condenser.last_degraded is True
        assert result.action.summary  # not wiped

    async def test_llm_exception_degrades(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(llm=llm, max_size=10, keep_first=2)

        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        llm.acompletion = AsyncMock(side_effect=RuntimeError('provider down'))

        with patch.object(condenser, '_add_response_metadata'):
            result = await condenser.get_compaction(view)

        assert condenser.last_degraded is True
        assert result.action.summary
        assert 'degraded' in result.action.summary

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

        assert condenser.last_degraded is False
        assert result.action.summary == good_prose
        assert llm.acompletion.await_count == 2

    async def test_retry_exhausted_degrades(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(
            llm=llm,
            max_size=10,
            keep_first=2,
            min_prose_length=500,
            max_repair_attempts=2,
        )

        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        llm.acompletion = AsyncMock(return_value=_make_prose_response('still short'))

        with patch.object(condenser, '_add_response_metadata'):
            result = await condenser.get_compaction(view)

        assert condenser.last_degraded is True
        assert llm.acompletion.await_count == 3  # 1 initial + 2 retries

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
        assert condenser.last_degraded is False

    async def test_degrades_after_retries_exhausted(self):
        llm = _make_llm()
        condenser = StructuredSummaryCompactor(
            llm=llm, max_size=10, keep_first=2, max_repair_attempts=1
        )

        events = [_event(i) for i in range(8)]
        view = _make_view(events)

        llm.acompletion = AsyncMock(return_value=_make_prose_response('short'))

        with patch.object(condenser, '_add_response_metadata'):
            await condenser.get_compaction(view)

        assert llm.acompletion.await_count == 2
        assert condenser.last_degraded is True

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
        assert '<PREVIOUS SUMMARY>' in prompt
        assert '</PREVIOUS SUMMARY>' in prompt

    def test_prompt_includes_previous_summary_content(self):
        prompt = self._build_prompt(summary_text='Built X from scratch')
        assert 'Built X from scratch' in prompt

    def test_prompt_instructs_preserve_previous_narrative(self):
        prompt = self._build_prompt()
        assert 'preserve its narrative arc' in prompt.lower()

    def test_prompt_instructs_from_scratch_preservation(self):
        prompt = self._build_prompt()
        assert 'narrative arc' in prompt.lower()
        assert 'previous summary' in prompt.lower()

    def test_prompt_includes_event_digest_section(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [_event(1)]
        )
        assert '<EVENT DIGEST>' in prompt
        assert '</EVENT DIGEST>' in prompt

    def test_prompt_includes_recent_raw_events_section(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [_event(1)]
        )
        assert '<RECENT RAW EVENTS' in prompt

    def test_prompt_only_includes_last_5_raw_events(self):
        events = [_event(i, content=f'event {i}') for i in range(20)]
        prompt = self.condenser._build_condensation_prompt(_summary_event(0), events)
        raw_section = prompt[prompt.index('<RECENT RAW EVENTS') :]
        assert 'event 19' in raw_section
        assert 'event 15' in raw_section
        assert 'event 14' not in raw_section

    def test_prompt_includes_pruned_events(self):
        event = _event(42, content='Created autograd/tensor.py')
        prompt = self.condenser._build_condensation_prompt(_summary_event(0), [event])
        assert 'Created autograd/tensor.py' in prompt

    def test_prompt_has_priority_ordered_sections(self):
        prompt = self._build_prompt()
        assert 'UNRESOLVED & BLOCKING' in prompt
        assert 'NEXT STEPS' in prompt
        assert 'FAILED APPROACHES' in prompt
        assert 'ACCOMPLISHED & ARCHITECTURE' in prompt
        assert 'DECISIONS & RATIONALE' in prompt

    def test_prompt_has_budget_constraint(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [], char_limit=48000
        )
        assert 'BUDGET CONSTRAINT' in prompt
        assert '48000 characters' in prompt

    def test_prompt_budget_reflects_char_limit(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [], char_limit=12000
        )
        assert '12000 characters' in prompt

    def test_prompt_instructs_synthesized_user_goal_not_verbatim_quotes(self):
        prompt = self._build_prompt()
        assert 'GOAL CONTEXT' in prompt or 'goal context' in prompt.lower()
        assert 'Do NOT quote' in prompt or 'Never include' in prompt
        assert 'exact file paths' in prompt
        assert 'test names' in prompt
        assert 'exact error messages' in prompt
        assert 'User messages (verbatim)' not in prompt

    def test_prompt_instructs_failed_approaches(self):
        prompt = self._build_prompt()
        assert 'FAILED APPROACHES' in prompt
        assert 'not tool-level' in prompt.lower()

    def test_prompt_instructs_dense_markdown_not_filler(self):
        prompt = self._build_prompt()
        assert 'hyper-dense Markdown' in prompt
        assert 'conversational filler' in prompt.lower()

    def test_prompt_instructs_unverified_flag(self):
        prompt = self._build_prompt()
        assert '[UNVERIFIED]' in prompt


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
        assert 'PREVIOUS GOAL SYNTHESIS' in prompt
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
        assert 'PREVIOUS GOAL SYNTHESIS' in prompt
        assert 'Build a compiler with X constraints' in prompt

    def test_previous_goal_synthesis_omitted_when_no_prior_goal(self):
        summary_event = _summary_event(0, message='## UNRESOLVED\nNone')
        prompt = self.condenser._build_condensation_prompt(
            summary_event, [], char_limit=48000
        )
        assert 'PREVIOUS GOAL SYNTHESIS' not in prompt

    def test_prompt_includes_goal_section_instruction(self):
        prompt = self.condenser._build_condensation_prompt(
            _summary_event(0), [], char_limit=48000
        )
        assert '## USER GOAL' in prompt
        assert 'Highest Priority' in prompt


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
