"""Prompt templating utilities and helper data structures for agent messaging."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from itertools import islice
from typing import TYPE_CHECKING

from backend.core.message import Message, TextContent

if TYPE_CHECKING:
    from backend.ledger.observation.agent import PlaybookKnowledge
    from backend.orchestration.state.state import State
    from backend.persistence.data_models.knowledge_base import KnowledgeBaseSearchResult


@dataclass
class RuntimeInfo:
    """Lightweight container describing current runtime environment for prompts."""

    date: str
    available_hosts: dict[str, int] = field(default_factory=dict)
    additional_agent_instructions: str = ''
    custom_secrets_descriptions: dict[str, str] = field(default_factory=dict)
    working_dir: str = ''


@dataclass
class RepositoryInfo:
    """Information about a GitHub repository that has been cloned."""

    repo_name: str | None = None
    repo_directory: str | None = None
    branch_name: str | None = None


@dataclass
class ConversationInstructions:
    """Optional instructions the agent must follow throughout the conversation while addressing the user's initial task.

    Examples include

        1. Resolver instructions: you're responding to GitHub issue #1234, make sure to open a PR when you are done
        2. Slack instructions: make sure to check whether any of the context attached is relevant to the task <context_messages>
    """

    content: str = ''


class _UninitializedPromptManager:
    """Sentinel indicating a prompt manager hasn't been initialized yet.

    Provides better type safety than ``None`` for lazy-init patterns
    used by engines like locator and auditor.
    """


UNINITIALIZED_PROMPT_MANAGER = _UninitializedPromptManager()
"""Module-level sentinel instance — import this instead of duplicating the class."""


def _content_has_app_identity(content: str) -> bool:
    """True when the rendered system prompt already identifies as App (skip duplicate prefix)."""
    head = content.lstrip()[:80].lower()
    return head.startswith('you are app')


class PromptManager:
    """Manages prompt assembly using Python-based prompt builder (no Jinja2).

    Attributes:
        prompt_dir: Directory containing prompt .md partials.

    """

    def __init__(
        self,
        prompt_dir: str | None,
        system_prompt_filename: str = 'system_prompt',
    ) -> None:
        """Initialize prompt manager with the given prompt directory."""
        if prompt_dir is None:
            msg = 'Prompt directory is not set'
            raise ValueError(msg)
        self.prompt_dir: str = prompt_dir

    def get_system_message(self, **context) -> str:
        """Render system prompt via Python prompt builder and apply refinement."""
        import shutil

        from backend.engine.prompts.prompt_builder import build_system_prompt
        from backend.engine.tools.prompt import get_terminal_tool_name

        _on_windows = sys.platform == 'win32'
        _has_bash = bool(shutil.which('bash'))
        context.setdefault('is_windows', _on_windows and not _has_bash)
        context.setdefault('windows_with_bash', _on_windows and _has_bash)
        context.setdefault('terminal_tool_name', get_terminal_tool_name())
        system_message = build_system_prompt(**context).strip()
        return system_message

    def set_prompt_tier(self, tier: str) -> None:
        """Set a coarse prompt tier for subsequent system prompt rendering.

        Tiers are a lightweight mechanism to avoid always injecting large,
        rarely-needed blocks (e.g. repo lessons) into every turn.

        Known tiers: "base", "debug".
        """
        self._prompt_tier = tier

    def get_example_user_message(self) -> str:
        """Return the initial example user message (empty by default)."""
        return ''

    def build_workspace_context(
        self,
        repository_info: RepositoryInfo | None,
        runtime_info: RuntimeInfo | None,
        conversation_instructions: ConversationInstructions | None,
        repo_instructions: str = '',
    ) -> str:
        """Render the additional info / workspace context block."""
        from backend.engine.prompts.prompt_builder import (
            build_workspace_context as _build,
        )

        return _build(
            repository_info=repository_info,
            runtime_info=runtime_info,
            conversation_instructions=conversation_instructions,
            repo_instructions=repo_instructions,
        )

    def build_playbook_info(self, triggered_agents: list[PlaybookKnowledge]) -> str:
        """Render playbook info for triggered agents."""
        from backend.engine.prompts.prompt_builder import build_playbook_info as _build

        return _build(triggered_agents)

    def build_knowledge_base_info(
        self, kb_results: list[KnowledgeBaseSearchResult]
    ) -> str:
        """Render knowledge base search results."""
        from backend.engine.prompts.prompt_builder import (
            build_knowledge_base_info as _build,
        )

        return _build(kb_results)

    def add_turns_left_reminder(self, messages: list[Message], state: State) -> None:
        """Append reminder about remaining turns to the most recent user message."""
        if latest_user_message := next(
            islice(
                (
                    m
                    for m in reversed(messages)
                    if m.role == 'user'
                    and any((isinstance(c, TextContent) for c in m.content))
                ),
                1,
            ),
            None,
        ):
            turns_left = (
                state.iteration_flag.max_value - state.iteration_flag.current_value
            )
            reminder_text = (
                '\n\nENVIRONMENT REMINDER: You have '
                f'{turns_left} turns left to complete the task. '
                'When finished reply with <finish></finish>.'
            )
            latest_user_message.content.append(TextContent(text=reminder_text))


class OrchestratorPromptManager(PromptManager):
    """PromptManager subclass that injects orchestrator-specific defaults.

    Replaces the previous ``setattr`` monkey-patch in ``orchestrator.py``
    with a proper override, preserving type-safety and IDE navigability.
    """

    _IDENTITY_PREFIX = 'You are App agent.\n'

    def __init__(
        self,
        prompt_dir: str | None,
        system_prompt_filename: str = 'system_prompt',
        *,
        config: object | None = None,
        resolved_llm_model_id: str | None = None,
        app_config: object | None = None,
    ) -> None:
        super().__init__(prompt_dir, system_prompt_filename)
        self._config = config
        # Runtime-resolved model id (AppConfig + user settings live on LLMRegistry; AgentConfig often only references "llm").
        self._resolved_llm_model_id = (resolved_llm_model_id or '').strip()
        self._app_config = app_config
        # Populated dynamically by the orchestrator after MCP tools connect
        self.mcp_tool_names: list[str] = []
        self.mcp_tool_descriptions: dict[str, str] = {}
        # Per-server usage_hint lines from app MCP config (see MCPServerConfig.usage_hint)
        self.mcp_server_hints: list[dict[str, str]] = []

    def _active_llm_model_id(self) -> str:
        """Model id for self-identification in the system prompt."""
        if self._resolved_llm_model_id:
            return self._resolved_llm_model_id
        if self._app_config is not None and self._config is not None:
            try:
                llm_cfg = getattr(
                    self._app_config,
                    'get_llm_config_from_agent_config',
                    None,
                )
                if callable(llm_cfg):
                    resolved = llm_cfg(self._config)  # pylint: disable=not-callable
                    if resolved and hasattr(resolved, 'model') and resolved.model:
                        return str(resolved.model).strip()
            except Exception:
                pass
        return ''

    def get_system_message(self, **context: object) -> str:
        """Render with orchestrator defaults (config, cli_mode, identity prefix)."""
        if self._config is not None:
            context.setdefault('config', self._config)
            context.setdefault('cli_mode', True)

        # On Windows with bash available, tell the prompt to use bash
        # instructions (is_windows=False) since Git Bash is the active shell.
        import shutil

        _on_windows = sys.platform == 'win32'
        _has_bash = bool(shutil.which('bash'))
        context.setdefault('is_windows', _on_windows and not _has_bash)
        context.setdefault('windows_with_bash', _on_windows and _has_bash)
        context.setdefault('mcp_tool_names', self.mcp_tool_names)
        context.setdefault('mcp_tool_descriptions', self.mcp_tool_descriptions)
        context.setdefault('mcp_server_hints', self.mcp_server_hints)
        context.setdefault('active_llm_model', self._active_llm_model_id())
        content = super().get_system_message(**context)
        # Avoid duplicating identity: system_prompt already opens with the app identity.
        if not _content_has_app_identity(content):
            content = self._IDENTITY_PREFIX + content
        content = self._inject_scratchpad(content)
        tier = getattr(self, '_prompt_tier', 'base')
        if tier == 'debug':
            content = self._inject_lessons_learned(content)
        return content

    def _inject_lessons_learned(self, content: str) -> str:
        """Inject lessons learned from .app/lessons.md into the system prompt."""
        try:
            from backend.core.workspace_resolution import (
                get_effective_workspace_root,
                workspace_agent_state_dir,
            )

            root = get_effective_workspace_root()
            if root is None:
                return content
            lessons_path = workspace_agent_state_dir(root) / 'lessons.md'
            if not lessons_path.is_file():
                lessons_path = root / 'memories' / 'repo' / 'lessons.md'
                if not lessons_path.is_file():
                    return content

            with open(lessons_path, 'r', encoding='utf-8') as f:
                lessons = f.read().strip()

            if not lessons:
                return content

            # Keep only the last 3000 chars to avoid prompt bloat
            if len(lessons) > 3000:
                lessons = '... (earlier lessons truncated)\n' + lessons[-3000:]

            return (
                f'{content}\n\n'
                f'<REPOSITORY_LESSONS_LEARNED>\n'
                f'Historical insights and verified solutions for this codebase:\n'
                f'{lessons}\n'
                f'</REPOSITORY_LESSONS_LEARNED>'
            )
        except Exception:
            return content

    def _inject_scratchpad(self, content: str) -> str:
        """Append persistent scratchpad and working memory so they survive condensation."""
        try:
            from backend.engine.tools.note import (
                scratchpad_entries_for_prompt,
            )
            from backend.engine.tools.working_memory import (
                get_working_memory_prompt_block,
            )

            entries = scratchpad_entries_for_prompt()
            memory_blocks: list[str] = []
            if entries:
                lines: list[str] = []
                char_budget = 2000
                for key, value in entries:
                    line = f'  [{key}]: {value}'
                    if len('\n'.join(lines + [line])) > char_budget:
                        lines.append('  ... (additional notes truncated)')
                        break
                    lines.append(line)
                scratchpad_block = '\n'.join(lines)
                memory_blocks.append(
                    '<WORKING_SCRATCHPAD>\n'
                    'Your persistent notes (survive context condensation):\n'
                    f'{scratchpad_block}\n'
                    '</WORKING_SCRATCHPAD>'
                )
            working_memory_block = get_working_memory_prompt_block()
            if working_memory_block:
                memory_blocks.append(working_memory_block)
            if not memory_blocks:
                return content
            return f'{content}\n\n' + '\n\n'.join(memory_blocks)
        except Exception:
            return content
