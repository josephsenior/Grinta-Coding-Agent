"""Prompt templating utilities and helper data structures for agent messaging."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from itertools import islice
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, Template

from backend.core.message import Message, TextContent

if TYPE_CHECKING:
    from backend.controller.state.state import State
    from backend.events.observation.agent import PlaybookKnowledge
    from backend.storage.data_models.knowledge_base import KnowledgeBaseSearchResult


@dataclass
class RuntimeInfo:
    """Lightweight container describing current runtime environment for prompts."""

    date: str
    available_hosts: dict[str, int] = field(default_factory=dict)
    additional_agent_instructions: str = ""
    custom_secrets_descriptions: dict[str, str] = field(default_factory=dict)
    working_dir: str = ""


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

    content: str = ""


class _UninitializedPromptManager:
    """Sentinel indicating a prompt manager hasn't been initialized yet.

    Provides better type safety than ``None`` for lazy-init patterns
    used by engines like locator and auditor.
    """


UNINITIALIZED_PROMPT_MANAGER = _UninitializedPromptManager()
"""Module-level sentinel instance — import this instead of duplicating the class."""


def _content_has_forge_identity(content: str) -> bool:
    """True when the rendered system prompt already identifies as Forge (skip duplicate prefix)."""
    head = content.lstrip()[:80].lower()
    return head.startswith("you are forge")


class PromptManager:
    """Manages prompt templates and includes information from the user's workspace micro-agents and global micro-agents.

    This class is dedicated to loading and rendering prompts (system prompt, user prompt).

    Attributes:
        prompt_dir: Directory containing prompt templates.

    """

    def __init__(
        self,
        prompt_dir: str | None,
        system_prompt_filename: str = "system_prompt.j2",
    ) -> None:
        """Initialize Jinja environment and load core prompt templates."""
        if prompt_dir is None:
            msg = "Prompt directory is not set"
            raise ValueError(msg)
        self.prompt_dir: str = prompt_dir

        # We include orchestrator prompts as a shared fallback for common templates.
        # IMPORTANT: system prompts must always come from the engine's own prompt_dir,
        # otherwise a missing engine prompt could accidentally fall back to the
        # orchestrator's system prompt.
        shared_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "engines",
            "orchestrator",
            "prompts",
        )
        search_paths = [prompt_dir]
        if os.path.isdir(shared_dir) and shared_dir not in search_paths:
            search_paths.append(shared_dir)

        # nosec B701 - Template rendering for prompts (not HTML), autoescape enabled
        self.env = Environment(loader=FileSystemLoader(search_paths), autoescape=True)
        self._system_env = Environment(
            loader=FileSystemLoader([prompt_dir]), autoescape=True
        )
        self.system_template = self._load_template(
            system_prompt_filename, env=self._system_env, template_dir=prompt_dir
        )
        self.user_template: Template = self._load_template("user_prompt.j2")
        self.additional_info_template: Template = self._load_template(
            "additional_info.j2"
        )
        self.playbook_info_template: Template = self._load_template("playbook_info.j2")
        self.knowledge_base_info_template: Template = self._load_template(
            "knowledge_base_info.j2"
        )

    def _load_template(
        self,
        template_name: str,
        *,
        env: Environment | None = None,
        template_dir: str | None = None,
    ) -> Template:
        """Load a template from the prompt directory.

        Args:
            template_name: Full filename of the template to load, including the .j2 extension.

        Returns:
            The loaded Jinja2 template.

        Raises:
            FileNotFoundError: If the template file is not found.

        """
        env = env or self.env
        template_dir = template_dir or self.prompt_dir
        try:
            return env.get_template(template_name)
        except Exception as e:
            template_path = os.path.join(template_dir, template_name)
            msg = f"Prompt file {template_path} not found"
            raise FileNotFoundError(msg) from e


    def get_system_message(self, **context) -> str:
        """Render system prompt with optional context and apply refinement helpers."""
        from backend.engines.orchestrator.tools.prompt import refine_prompt

        # On Windows, set is_windows=False when bash is available so the
        # system prompt teaches bash (not PowerShell) — matching the shell
        # that will actually execute commands.
        import shutil
        _on_windows = sys.platform == "win32"
        context.setdefault("is_windows", _on_windows and not shutil.which("bash"))
        system_message = self.system_template.render(**context).strip()
        return refine_prompt(system_message)

    def set_prompt_tier(self, tier: str) -> None:
        """Set a coarse prompt tier for subsequent system prompt rendering.

        Tiers are a lightweight mechanism to avoid always injecting large,
        rarely-needed blocks (e.g. repo lessons) into every turn.

        Known tiers: "base", "debug".
        """
        self._prompt_tier = tier

    def get_example_user_message(self) -> str:
        """This is an initial user message that can be provided to the agent.

        before *actual* user instructions are provided.

        It can be used to provide a demonstration of how the agent
        should behave in order to solve the user's task. And it may
        optionally contain some additional context about the user's task.
        These additional context will convert the current generic agent
        into a more specialized agent that is tailored to the user's task.
        """
        return self.user_template.render().strip()

    def build_workspace_context(
        self,
        repository_info: RepositoryInfo | None,
        runtime_info: RuntimeInfo | None,
        conversation_instructions: ConversationInstructions | None,
        repo_instructions: str = "",
    ) -> str:
        """Renders the additional info template with the stored repository/runtime info."""
        return self.additional_info_template.render(
            repository_info=repository_info,
            repository_instructions=repo_instructions,
            runtime_info=runtime_info,
            conversation_instructions=conversation_instructions,
        ).strip()

    def build_playbook_info(self, triggered_agents: list[PlaybookKnowledge]) -> str:
        """Renders the playbook info template with the triggered agents.

        Args:
            triggered_agents: A list of PlaybookKnowledge objects containing information
                              about triggered playbooks.

        """
        return self.playbook_info_template.render(
            triggered_agents=triggered_agents
        ).strip()

    def build_knowledge_base_info(
        self, kb_results: list[KnowledgeBaseSearchResult]
    ) -> str:
        """Renders the knowledge base info template with the search results.

        Args:
            kb_results: A list of KnowledgeBaseSearchResult objects.

        """
        return self.knowledge_base_info_template.render(kb_results=kb_results).strip()

    def add_turns_left_reminder(self, messages: list[Message], state: State) -> None:
        """Append reminder about remaining turns to the most recent user message."""
        if latest_user_message := next(
            islice(
                (
                    m
                    for m in reversed(messages)
                    if m.role == "user"
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
                "\n\nENVIRONMENT REMINDER: You have "
                f"{turns_left} turns left to complete the task. "
                "When finished reply with <finish></finish>."
            )
            latest_user_message.content.append(TextContent(text=reminder_text))


class OrchestratorPromptManager(PromptManager):
    """PromptManager subclass that injects orchestrator-specific defaults.

    Replaces the previous ``setattr`` monkey-patch in ``orchestrator.py``
    with a proper override, preserving type-safety and IDE navigability.
    """

    _IDENTITY_PREFIX = "You are Forge agent.\n"

    def __init__(
        self,
        prompt_dir: str | None,
        system_prompt_filename: str = "system_prompt.j2",
        *,
        config: object | None = None,
        resolved_llm_model_id: str | None = None,
        forge_config: object | None = None,
    ) -> None:
        super().__init__(prompt_dir, system_prompt_filename)
        self._config = config
        # Runtime-resolved model id (ForgeConfig + user settings live on LLMRegistry; AgentConfig often only references "llm").
        self._resolved_llm_model_id = (resolved_llm_model_id or "").strip()
        self._forge_config = forge_config
        # Populated dynamically by the orchestrator after MCP tools connect
        self.mcp_tool_names: list[str] = []
        self.mcp_tool_descriptions: dict[str, str] = {}
        # Per-server usage_hint lines from Forge MCP config (see MCPServerConfig.usage_hint)
        self.mcp_server_hints: list[dict[str, str]] = []

    def _active_llm_model_id(self) -> str:
        """Model id for self-identification in the system prompt."""
        if self._resolved_llm_model_id:
            return self._resolved_llm_model_id
        if self._forge_config is not None and self._config is not None:
            try:
                llm_cfg = getattr(
                    self._forge_config,
                    "get_llm_config_from_agent_config",
                    None,
                )
                if callable(llm_cfg):
                    resolved = llm_cfg(self._config)
                    if resolved and hasattr(resolved, "model") and resolved.model:
                        return str(resolved.model).strip()
            except Exception:
                pass
        return ""

    def get_system_message(self, **context: object) -> str:
        """Render with orchestrator defaults (config, cli_mode, identity prefix)."""
        if self._config is not None:
            context.setdefault("config", self._config)
            context.setdefault("cli_mode", getattr(self._config, "cli_mode", False))

        # On Windows with bash available, tell the prompt to use bash
        # instructions (is_windows=False) since Git Bash is the active shell.
        import shutil
        _on_windows = sys.platform == "win32"
        context.setdefault("is_windows", _on_windows and not shutil.which("bash"))
        context.setdefault("mcp_tool_names", self.mcp_tool_names)
        context.setdefault("mcp_tool_descriptions", self.mcp_tool_descriptions)
        context.setdefault("mcp_server_hints", self.mcp_server_hints)
        context.setdefault("active_llm_model", self._active_llm_model_id())
        content = super().get_system_message(**context)
        # Avoid duplicating identity: system_prompt.j2 already opens with "You are Forge, ..."
        if not _content_has_forge_identity(content):
            content = self._IDENTITY_PREFIX + content
        content = self._inject_scratchpad(content)
        tier = getattr(self, "_prompt_tier", "base")
        if tier == "debug":
            content = self._inject_lessons_learned(content)
        return content

    def _inject_lessons_learned(self, content: str) -> str:
        """Inject lessons learned from .Forge/lessons.md into the system prompt."""
        try:
            from backend.core.workspace_resolution import get_effective_workspace_root

            root = get_effective_workspace_root()
            if root is None:
                return content
            lessons_path = root / ".Forge" / "lessons.md"
            if not lessons_path.is_file():
                lessons_path = root / "memories" / "repo" / "lessons.md"
                if not lessons_path.is_file():
                    return content

            with open(lessons_path, "r", encoding="utf-8") as f:
                lessons = f.read().strip()

            if not lessons:
                return content

            # Keep only the last 3000 chars to avoid prompt bloat
            if len(lessons) > 3000:
                lessons = "... (earlier lessons truncated)\n" + lessons[-3000:]

            return (
                f"{content}\n\n"
                f"<REPOSITORY_LESSONS_LEARNED>\n"
                f"Historical insights and verified solutions for this codebase:\n"
                f"{lessons}\n"
                f"</REPOSITORY_LESSONS_LEARNED>"
            )
        except Exception:
            return content

    def _inject_scratchpad(self, content: str) -> str:
        """Append persistent scratchpad notes so they survive context condensation."""
        try:
            from backend.engines.orchestrator.tools.memory_manager_temp1 import (
                scratchpad_entries_for_prompt,
            )

            entries = scratchpad_entries_for_prompt()
            if not entries:
                return content
            lines: list[str] = []
            char_budget = 2000
            for key, value in entries:
                line = f"  [{key}]: {value}"
                if len("\n".join(lines + [line])) > char_budget:
                    lines.append("  ... (additional notes truncated)")
                    break
                lines.append(line)
            scratchpad_block = "\n".join(lines)
            return (
                f"{content}\n\n"
                f"<WORKING_SCRATCHPAD>\n"
                f"Your persistent notes (survive context condensation):\n"
                f"{scratchpad_block}\n"
                f"</WORKING_SCRATCHPAD>"
            )
        except Exception:
            return content
