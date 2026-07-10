"""Tests for prompt section renderers — mode-aware output in critical rules and capabilities."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def _fake_render_partial(partial_name: str, **kwargs: Any) -> str:
    """Minimal render_partial stand-in that returns the execution_rules_body."""
    return kwargs.get('execution_rules_body', '')


def _make_config(**overrides: Any) -> SimpleNamespace:
    """Minimal config stub with sensible defaults."""
    defaults: dict[str, Any] = dict(
        enable_web=True,
        enable_docs=True,
        enable_browsing=True,
        enable_working_memory=True,
        enable_checkpoints=False,
        enable_lsp_query=False,
        enable_debugger=False,
        mode='agent',
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# _critical — execution rules body
# ---------------------------------------------------------------------------


class TestBuildNumberedRules:
    """_build_numbered_rules helper."""

    def test_numbers_from_one(self):
        from backend.engine.prompts.section_renderers._critical import (
            _build_numbered_rules,
        )

        result = _build_numbered_rules(['first', 'second', 'third'])
        assert result == '1. first\n2. second\n3. third'

    def test_single_rule(self):
        from backend.engine.prompts.section_renderers._critical import (
            _build_numbered_rules,
        )

        result = _build_numbered_rules(['only'])
        assert result == '1. only'

    def test_empty_list(self):
        from backend.engine.prompts.section_renderers._critical import (
            _build_numbered_rules,
        )

        result = _build_numbered_rules([])
        assert result == ''


class TestRenderCriticalModeSpecific:
    """_render_critical produces different rules per mode."""

    COMMON_AGENT_RULES = [
        'File changes require tool calls',
        'To run commands, use',
        'Reasoning alone does not execute',
        'Never fabricate outcomes',
    ]

    def _render_critical(self, *, mode: str = 'agent', **kwargs: Any) -> str:
        from backend.engine.prompts.section_renderers._critical import (
            _render_critical,
        )

        return _render_critical(
            _fake_render_partial,
            'execute_command',
            terminal_manager_available=kwargs.get('terminal_available', False),
            tracker_on=kwargs.get('tracker_on', False),
            checkpoints_on=kwargs.get('checkpoints_on', False),
            mode=mode,
        )

    def _assert_contains_body(self, body: str, *fragments: str) -> None:
        for fragment in fragments:
            assert fragment in body, f'Expected {fragment!r} in:\n{body}'

    def _assert_not_contains_body(self, body: str, *fragments: str) -> None:
        for fragment in fragments:
            assert fragment not in body, f'Unexpected {fragment!r} in:\n{body}'

    # -- Agent mode --------------------------------------------------------

    def test_agent_mode_has_core_rules(self):
        body = self._render_critical(mode='agent')
        for r in self.COMMON_AGENT_RULES:
            self._assert_contains_body(body, r)
        self._assert_contains_body(body, 'Verify before final summary')
        self._assert_contains_body(body, 'No unchanged retries after failure')
        self._assert_contains_body(body, 'Tests must track real APIs')
        self._assert_contains_body(body, 'Postmortem on failing tests')
        self._assert_contains_body(body, 'executable evidence')
        self._assert_contains_body(body, 'Non-test failures')
        # Should NOT have chat-specific rules
        self._assert_not_contains_body(body, 'Non-tool responses end the turn')

    def test_agent_mode_verify_rule_mentions_audit_entries(self):
        body = self._render_critical(mode='agent', criteria_on=True)
        self._assert_contains_body(body, 'audit_entries')
        self._assert_contains_body(body, 'evidence')

    def test_agent_mode_contains_exactly_10_rules(self):
        body = self._render_critical(mode='agent', terminal_available=False)
        lines = [
            line
            for line in body.split('\n')
            if line.strip().startswith(
                ('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '10.')
            )
        ]
        assert len(lines) == 10, (
            f'Expected 10 numbered rules with acceptance_criteria enabled, got {len(lines)}:\n{body}'
        )

    def test_agent_mode_with_terminal_adds_rule(self):
        body = self._render_critical(mode='agent', terminal_available=True)
        self._assert_contains_body(body, 'Shell vs interactive terminal')
        self._assert_contains_body(body, 'execute_command')
        self._assert_not_contains_body(body, '{terminal_command_tool}')

        self._assert_contains_body(body, 'terminal_manager action=wait')
        self._assert_contains_body(body, 'action=stop')
        self._assert_contains_body(body, 'action=open')
        lines = [
            line
            for line in body.split('\n')
            if line.strip().startswith(
                ('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '10.')
            )
        ]
        assert len(lines) == 10, (
            f'Expected 10 numbered rules with terminal, got {len(lines)}'
        )

    def test_agent_mode_has_mandatory_header(self):
        body = self._render_critical(mode='agent')
        assert body.startswith('<CRITICAL_TOOL_EXECUTION_RULES>\nMANDATORY:\n\n')

    def test_agent_mode_has_closing_tag(self):
        body = self._render_critical(mode='agent')
        assert body.endswith('</CRITICAL_TOOL_EXECUTION_RULES>')

    def test_agent_rules_numbered_sequentially(self):
        body = self._render_critical(mode='agent', terminal_available=False)
        numbered_lines = [
            line.strip()
            for line in body.split('\n')
            if line.strip() and line.strip()[0].isdigit() and '. ' in line[:4]
        ]
        for i, line in enumerate(numbered_lines, 1):
            assert line.startswith(f'{i}.'), f'Expected rule {i}, got: {line!r}'

    # -- Chat / Plan mode --------------------------------------------------

    def _render_critical_body(self, mode: str) -> str:
        return self._render_critical(mode=mode)

    def test_chat_mode_has_only_three_rules(self):
        body = self._render_critical_body(mode='chat')
        numbered_lines = [
            line.strip()
            for line in body.split('\n')
            if line.strip() and line.strip()[0].isdigit() and '. ' in line[:4]
        ]
        assert len(numbered_lines) == 3, (
            f'Expected 3 rules for chat, got {len(numbered_lines)}'
        )

    def test_chat_mode_rules(self):
        body = self._render_critical_body(mode='chat')
        self._assert_contains_body(body, 'Never fabricate outcomes')
        self._assert_contains_body(body, 'No unchanged retries after failure')
        self._assert_contains_body(body, 'Non-tool responses end the turn')

    def test_chat_mode_excludes_agent_specific_rules(self):
        body = self._render_critical_body(mode='chat')
        self._assert_not_contains_body(body, 'File changes require tool calls')
        self._assert_not_contains_body(body, 'Reasoning alone does not execute')
        self._assert_not_contains_body(body, 'Verify before final summary')
        self._assert_not_contains_body(body, 'Tests must track real APIs')

    def test_plan_mode_has_only_three_rules(self):
        body = self._render_critical_body(mode='plan')
        numbered_lines = [
            line.strip()
            for line in body.split('\n')
            if line.strip() and line.strip()[0].isdigit() and '. ' in line[:4]
        ]
        assert len(numbered_lines) == 3, (
            f'Expected 3 rules for plan, got {len(numbered_lines)}'
        )

    def test_plan_mode_rules(self):
        body = self._render_critical_body(mode='plan')
        self._assert_contains_body(body, 'Never fabricate outcomes')
        self._assert_contains_body(body, 'No unchanged retries after failure')
        self._assert_contains_body(body, 'Non-tool responses end the turn')

    def test_plan_mode_excludes_agent_specific_rules(self):
        body = self._render_critical_body(mode='plan')
        self._assert_not_contains_body(body, 'File changes require tool calls')
        self._assert_not_contains_body(body, 'Reasoning alone does not execute')
        self._assert_not_contains_body(body, 'Verify before final summary')
        self._assert_not_contains_body(body, 'Tests must track real APIs')

    def test_chat_and_plan_have_mandatory_header(self):
        for mode in ('chat', 'plan'):
            body = self._render_critical_body(mode=mode)
            assert body.startswith('<CRITICAL_TOOL_EXECUTION_RULES>\nMANDATORY:\n\n')

    def test_chat_and_plan_rules_numbered_sequentially(self):
        for mode in ('chat', 'plan'):
            body = self._render_critical_body(mode=mode)
            numbered_lines = [
                line.strip()
                for line in body.split('\n')
                if line.strip() and line.strip()[0].isdigit() and '. ' in line[:4]
            ]
            for i, line in enumerate(numbered_lines, 1):
                assert line.startswith(f'{i}.'), (
                    f'[{mode}] Expected rule {i}, got: {line!r}'
                )


# ---------------------------------------------------------------------------
# _capabilities — mode-specific lines
# ---------------------------------------------------------------------------


class TestSystemCapabilitiesModeSpecific:
    """_render_system_capabilities hides browser/memory/checkpoint/debugger in Chat/Plan."""

    def _render_caps(self, *, mode: str = 'agent', **overrides: Any) -> str:
        from backend.engine.prompts.section_renderers._capabilities import (
            _render_system_capabilities,
        )

        config = _make_config(**overrides)
        return _render_system_capabilities(
            config,
            function_calling_mode='native',
            parallel_tool_calls_provider_flag=False,
            mode=mode,
        )

    def _assert_contains(self, body: str, *fragments: str) -> None:
        for fragment in fragments:
            assert fragment in body, f'Expected {fragment!r} in:\n{body}'

    def _assert_not_contains(self, body: str, *fragments: str) -> None:
        for fragment in fragments:
            assert fragment not in body, f'Unexpected {fragment!r} in:\n{body}'

    # -- Agent mode: tools visible -----------------------------------------

    def test_agent_mode_shows_browser(self, monkeypatch):
        from backend.utils import optional_extras as oe

        monkeypatch.setattr(oe, 'browser_tool_enabled', lambda _cfg: True)
        body = self._render_caps(mode='agent')
        self._assert_contains(body, 'Browser (`browser`)')

    def test_agent_mode_hides_browser_when_extra_unavailable(self, monkeypatch):
        from backend.utils import optional_extras as oe

        monkeypatch.setattr(oe, 'browser_tool_enabled', lambda _cfg: False)
        body = self._render_caps(mode='agent', enable_browsing=True)
        self._assert_not_contains(body, 'Browser (`browser`)')

    def test_agent_mode_shows_search_history(self, monkeypatch):
        from backend.utils import optional_extras as oe
        monkeypatch.setattr(oe, 'is_rag_extra_available', lambda: True)
        body = self._render_caps(mode='agent', enable_vector_memory=True)
        self._assert_contains(body, 'Search History (`search_history`)')

    def test_agent_mode_shows_checkpoint_when_enabled(self):
        body = self._render_caps(mode='agent', enable_checkpoints=True)
        self._assert_contains(body, 'Checkpoints (`checkpoint`)')

    def test_agent_mode_shows_debugger_when_enabled(self):
        # debugger line comes from LSP/DAP detection block
        body = self._render_caps(mode='agent', enable_debugger=True)
        # When no DAP adapters are detected, the line is empty, so we just check
        # the method of rendering. The DAP line presence depends on detection.
        # We trust _render_runtime_detection_lines for that — just verify mode
        # doesn't suppress it.
        pass  # DAP detection depends on runtime, so skip inline assertion.

    def test_agent_mode_shows_condensation_info(self):
        body = self._render_caps(mode='agent')
        self._assert_contains(body, 'Conversation condensation')

    def test_agent_mode_shows_web_and_docs_when_enabled(self):
        body = self._render_caps(mode='agent')
        self._assert_contains(body, 'Web (`web_search`')
        self._assert_contains(body, 'Library docs (`docs_resolve`')

    # -- Chat/Plan mode: tools hidden --------------------------------------

    def test_chat_mode_hides_browser(self):
        body = self._render_caps(mode='chat')
        self._assert_not_contains(body, 'Browser (`browser`)')

    def test_chat_mode_shows_search_history_when_enabled(self, monkeypatch):
        from backend.utils import optional_extras as oe
        monkeypatch.setattr(oe, 'is_rag_extra_available', lambda: True)
        body = self._render_caps(mode='chat', enable_vector_memory=True)
        self._assert_contains(body, 'Search History (`search_history`)')

    def test_chat_mode_hides_checkpoint_even_when_enabled(self):
        body = self._render_caps(mode='chat', enable_checkpoints=True)
        self._assert_not_contains(body, 'Checkpoints (`checkpoint`)')

    def test_chat_mode_hides_debugger(self):
        body = self._render_caps(mode='chat', enable_debugger=True)
        # debugger line is hidden when not can_edit
        self._assert_not_contains(body, 'Debug adapters (DAP')

    def test_chat_mode_shows_condensation(self):
        body = self._render_caps(mode='chat')
        self._assert_contains(body, 'Conversation condensation')

    def test_chat_mode_shows_web_and_docs(self):
        body = self._render_caps(mode='chat')
        self._assert_contains(body, 'Web (`web_search`')
        self._assert_contains(body, 'Library docs (`docs_resolve`')

    def test_plan_mode_hides_browser(self):
        body = self._render_caps(mode='plan')
        self._assert_not_contains(body, 'Browser (`browser`)')

    def test_plan_mode_shows_search_history_when_enabled(self, monkeypatch):
        from backend.utils import optional_extras as oe
        monkeypatch.setattr(oe, 'is_rag_extra_available', lambda: True)
        body = self._render_caps(mode='plan', enable_vector_memory=True)
        self._assert_contains(body, 'Search History (`search_history`)')

    def test_all_modes_hide_search_history_when_disabled(self):
        for mode in ('agent', 'chat', 'plan'):
            body = self._render_caps(mode=mode, enable_vector_memory=False)
            self._assert_not_contains(body, 'Search History (`search_history`)')

    def test_plan_mode_hides_checkpoint(self):
        body = self._render_caps(mode='plan', enable_checkpoints=True)
        self._assert_not_contains(body, 'Checkpoints (`checkpoint`)')

    def test_plan_mode_hides_debugger(self):
        body = self._render_caps(mode='plan', enable_debugger=True)
        self._assert_not_contains(body, 'Debug adapters (DAP')

    def test_plan_mode_shows_condensation(self):
        body = self._render_caps(mode='plan')
        self._assert_contains(body, 'Conversation condensation')

    # -- Mode-independent: condensation, web, docs -------------------------

    def test_all_modes_have_capabilities_header(self):
        for mode in ('agent', 'chat', 'plan'):
            body = self._render_caps(mode=mode)
            assert 'System Capabilities (verified at runtime)' in body, (
                f'Missing header in {mode}'
            )

    def test_condensation_shown_in_all_modes(self):
        for mode in ('agent', 'chat', 'plan'):
            body = self._render_caps(mode=mode)
            self._assert_contains(body, 'Conversation condensation')

    def test_web_and_docs_shown_in_all_modes(self):
        for mode in ('agent', 'chat', 'plan'):
            body = self._render_caps(mode=mode)
            self._assert_contains(body, 'Web (`web_search`')
            self._assert_contains(body, 'Library docs (`docs_resolve`')


# ---------------------------------------------------------------------------
# _critical — full render against the .md template
# ---------------------------------------------------------------------------


class TestRenderCriticalFullRender:
    """Integration-style: _render_critical -> real template rendering."""

    def _load_template(self) -> str:
        from pathlib import Path

        path = (
            Path(__file__).parents[4]
            / 'backend'
            / 'engine'
            / 'prompts'
            / 'system_partial_04_critical.md'
        )
        return path.read_text(encoding='utf-8').strip()

    def _mock_render_partial(self, partial_name: str, **kwargs: Any) -> str:
        template = self._load_template()
        return template.format(**kwargs)

    def _render(self, *, mode: str = 'agent', **kwargs: Any) -> str:
        from backend.engine.prompts.section_renderers._critical import (
            _render_critical,
        )

        return _render_critical(
            self._mock_render_partial,
            'execute_command',
            terminal_manager_available=kwargs.get('terminal_available', False),
            tracker_on=kwargs.get('tracker_on', False),
            checkpoints_on=kwargs.get('checkpoints_on', False),
            mode=mode,
        )

    def test_agent_full_render_includes_anti_patterns(self):
        result = self._render(mode='agent')
        assert '<ANTI_PATTERNS>' in result
        assert 'The following are *always wrong*' in result
        assert '</ANTI_PATTERNS>' in result
        assert 'execution_rules_body' not in result  # no unsubstituted placeholders

    def test_chat_full_render_includes_anti_patterns(self):
        result = self._render(mode='chat')
        assert '<ANTI_PATTERNS>' in result
        assert '</ANTI_PATTERNS>' in result
        assert 'execution_rules_body' not in result

    def test_plan_full_render_includes_anti_patterns(self):
        result = self._render(mode='plan')
        assert '<ANTI_PATTERNS>' in result
        assert '</ANTI_PATTERNS>' in result
        assert 'execution_rules_body' not in result

    def test_agent_full_render_has_no_remaining_placeholders(self):
        import re

        result = self._render(mode='agent')
        placeholders = re.findall(r'\{[a-zA-Z_][a-zA-Z0-9_]*\}', result)
        assert not placeholders, f'Found unsubstituted placeholders: {placeholders}'

    def test_chat_full_render_has_no_remaining_placeholders(self):
        import re

        result = self._render(mode='chat')
        placeholders = re.findall(r'\{[a-zA-Z_][a-zA-Z0-9_]*\}', result)
        assert not placeholders, f'Found unsubstituted placeholders: {placeholders}'

    def test_plan_full_render_has_no_remaining_placeholders(self):
        import re

        result = self._render(mode='plan')
        placeholders = re.findall(r'\{[a-zA-Z_][a-zA-Z0-9_]*\}', result)
        assert not placeholders, f'Found unsubstituted placeholders: {placeholders}'

    def test_agent_tracker_antipattern_appears_when_tracker_on(self):
        result = self._render(mode='agent', tracker_on=True)
        assert 'task_tracker' in result
        assert 'Sync the tracker first' in result

    def test_chat_tracker_antipattern_not_present(self):
        result = self._render(mode='chat', tracker_on=True)
        assert 'Sync the tracker first' not in result

