"""Prompt templating utilities and helper data structures for agent messaging."""

from __future__ import annotations

import os
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
        # nosec B701 - Template rendering for prompts (not HTML), autoescape enabled
        self.env = Environment(loader=FileSystemLoader(prompt_dir), autoescape=True)
        self.system_template: Template = self._load_template(system_prompt_filename)
        self.user_template: Template = self._load_template("user_prompt.j2")
        self.additional_info_template: Template = self._load_template(
            "additional_info.j2"
        )
        self.playbook_info_template: Template = self._load_template("playbook_info.j2")
        self.knowledge_base_info_template: Template = self._load_template(
            "knowledge_base_info.j2"
        )

    def _load_template(self, template_name: str) -> Template:
        """Load a template from the prompt directory.

        Args:
            template_name: Full filename of the template to load, including the .j2 extension.

        Returns:
            The loaded Jinja2 template.

        Raises:
            FileNotFoundError: If the template file is not found.

        """
        try:
            return self.env.get_template(template_name)
        except Exception as e:
            template_path = os.path.join(self.prompt_dir, template_name)
            msg = f"Prompt file {template_path} not found"
            raise FileNotFoundError(msg) from e

    def get_system_message(self, **context) -> str:
        """Render system prompt with optional context and apply refinement helpers."""
        from backend.engines.orchestrator.tools.prompt import refine_prompt

        system_message = self.system_template.render(**context).strip()
        return refine_prompt(system_message)

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
            reminder_text = f"\n\nENVIRONMENT REMINDER: You have {
                state.iteration_flag.max_value - state.iteration_flag.current_value
            } turns left to complete the task. When finished reply with <finish></finish>."
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
    ) -> None:
        super().__init__(prompt_dir, system_prompt_filename)
        self._config = config

    def get_system_message(self, **context: object) -> str:
        """Render with orchestrator defaults (config, cli_mode, identity prefix)."""
        if self._config is not None:
            context.setdefault("config", self._config)
            context.setdefault("cli_mode", getattr(self._config, "cli_mode", False))
        content = super().get_system_message(**context)
        if self._IDENTITY_PREFIX.strip() not in content:
            content = self._IDENTITY_PREFIX + content
        return content
