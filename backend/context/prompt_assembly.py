"""Prompt assembly helpers for workspace context and knowledge recall.

Extracted from :class:`~backend.context.conversation_memory.ContextMemory`
to reduce file size and improve cohesion.  These functions build
``Message`` objects from ``RecallObservation`` events and delegate to
:class:`~backend.utils.prompt.PromptManager` for template rendering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from backend.core.enums import RecallType
from backend.core.logger import app_logger as logger
from backend.core.message import ImageContent, Message, TextContent
from backend.ledger.event import Event
from backend.ledger.observation.agent import PlaybookKnowledge, RecallObservation
from backend.utils.prompt import (
    ConversationInstructions,
    PromptManager,
    RepositoryInfo,
    RuntimeInfo,
)

if TYPE_CHECKING:
    from backend.core.config.agent_config import AgentConfig


# ------------------------------------------------------------------
# Recall observation → message conversion
# ------------------------------------------------------------------


def process_recall_observation(
    obs: RecallObservation,
    current_index: int,
    events: list[Event],
    agent_config: AgentConfig,
    prompt_manager: PromptManager,
) -> list[Message]:
    """Convert a RecallObservation into LLM-ready messages."""
    if not agent_config.enable_prompt_extensions:
        return []

    recall_type: RecallType | str | None = getattr(obs, 'recall_type', None)
    if recall_type == RecallType.WORKSPACE_CONTEXT:
        return _process_workspace_context_recall(obs, agent_config, prompt_manager)
    if recall_type == RecallType.KNOWLEDGE:
        return _process_knowledge_recall(
            obs,
            current_index,
            events,
            agent_config,
            prompt_manager,
        )
    logger.debug('Unknown recall type encountered: %s', recall_type)
    return []


# ------------------------------------------------------------------
# Workspace context
# ------------------------------------------------------------------


def _process_workspace_context_recall(
    obs: RecallObservation,
    agent_config: AgentConfig,
    prompt_manager: PromptManager,
) -> list[Message]:
    repo_info = _create_repo_info(obs)
    runtime_info = _create_runtime_info(obs)
    conversation_instructions = _create_conversation_instructions(obs)
    repo_instructions = obs.repo_instructions or ''
    filtered_agents = _filter_playbooks(obs, agent_config)

    has_content = _has_workspace_content(
        repo_info,
        runtime_info,
        repo_instructions,
        conversation_instructions,
        filtered_agents,
    )
    if not has_content:
        return []

    message_content = _build_message_content(
        repo_info,
        runtime_info,
        conversation_instructions,
        repo_instructions,
        filtered_agents,
        prompt_manager,
    )
    return [Message(role='user', content=message_content)]


def _create_repo_info(obs: RecallObservation) -> RepositoryInfo | None:
    if obs.repo_name or obs.repo_directory:
        return RepositoryInfo(
            repo_name=obs.repo_name or '',
            repo_directory=obs.repo_directory or '',
            branch_name=obs.repo_branch or None,
        )
    return None


def _create_runtime_info(obs: RecallObservation) -> RuntimeInfo:
    date = obs.date
    if obs.runtime_hosts or obs.additional_agent_instructions:
        return RuntimeInfo(
            available_hosts=obs.runtime_hosts,
            additional_agent_instructions=obs.additional_agent_instructions,
            date=date,
            custom_secrets_descriptions=obs.custom_secrets_descriptions,
            working_dir=obs.working_dir,
        )
    return RuntimeInfo(
        date=date,
        custom_secrets_descriptions=obs.custom_secrets_descriptions,
        working_dir=obs.working_dir,
    )


def _create_conversation_instructions(
    obs: RecallObservation,
) -> ConversationInstructions | None:
    if obs.conversation_instructions:
        return ConversationInstructions(content=obs.conversation_instructions)
    return None


def _filter_playbooks(
    obs: RecallObservation,
    agent_config: AgentConfig,
) -> list[PlaybookKnowledge]:
    if not obs.playbook_knowledge:
        return []
    return [
        agent
        for agent in obs.playbook_knowledge
        if agent.name not in agent_config.disabled_playbooks
    ]


def _has_workspace_content(
    repo_info: RepositoryInfo | None,
    runtime_info: RuntimeInfo,
    repo_instructions: str,
    conversation_instructions: ConversationInstructions | None,
    filtered_agents: list[PlaybookKnowledge],
) -> bool:
    has_repo = bool(repo_info and (repo_info.repo_name or repo_info.repo_directory))
    has_runtime = bool(runtime_info.date or runtime_info.custom_secrets_descriptions)
    has_instructions = (
        bool(repo_instructions.strip()) or conversation_instructions is not None
    )
    has_agents = bool(filtered_agents)
    return has_repo or has_runtime or has_instructions or has_agents


def _build_message_content(
    repo_info: RepositoryInfo | None,
    runtime_info: RuntimeInfo,
    conversation_instructions: ConversationInstructions | None,
    repo_instructions: str,
    filtered_agents: list[PlaybookKnowledge],
    prompt_manager: PromptManager,
) -> list[TextContent | ImageContent]:
    message_content: list[TextContent | ImageContent] = []

    has_repo = repo_info is not None and (
        repo_info.repo_name or repo_info.repo_directory
    )
    has_runtime = runtime_info is not None and (
        runtime_info.date or runtime_info.custom_secrets_descriptions
    )
    has_instructions = (
        bool(repo_instructions.strip()) or conversation_instructions is not None
    )

    if has_repo or has_runtime or has_instructions:
        formatted_workspace_text = prompt_manager.build_workspace_context(
            repository_info=repo_info,
            runtime_info=runtime_info,
            conversation_instructions=conversation_instructions,
            repo_instructions=repo_instructions,
        )
        message_content.append(TextContent(text=formatted_workspace_text))

    if filtered_agents:
        formatted_playbook_text = prompt_manager.build_playbook_info(
            triggered_agents=filtered_agents
        )
        message_content.append(TextContent(text=formatted_playbook_text))

    return message_content


# ------------------------------------------------------------------
# Knowledge recall
# ------------------------------------------------------------------


def _process_knowledge_recall(
    obs: RecallObservation,
    current_index: int,
    events: list[Event],
    agent_config: AgentConfig,
    prompt_manager: PromptManager,
) -> list[Message]:
    filtered_agents = filter_agents_in_playbook_obs(obs, current_index, events)
    if filtered_agents:
        filtered_agents = [
            agent
            for agent in filtered_agents
            if agent.name not in agent_config.disabled_playbooks
        ]

    formatted_parts: list[str] = []
    if filtered_agents:
        formatted_parts.append(
            prompt_manager.build_playbook_info(triggered_agents=filtered_agents)
        )

    kb_results = getattr(obs, 'knowledge_base_results', [])
    if kb_results:
        formatted_parts.append(
            prompt_manager.build_knowledge_base_info(kb_results=kb_results)
        )

    if formatted_parts:
        formatted_text = '\n\n'.join(formatted_parts)
        content_items: list[TextContent | ImageContent] = [
            TextContent(text=formatted_text)
        ]
        return [Message(role='user', content=content_items)]
    return []


def filter_agents_in_playbook_obs(
    obs: RecallObservation,
    current_index: int,
    events: list[Event],
) -> list[PlaybookKnowledge]:
    """Filter out agents that appear in earlier RecallObservations."""
    if obs.recall_type != RecallType.KNOWLEDGE:
        return obs.playbook_knowledge
    return [
        agent
        for agent in obs.playbook_knowledge
        if not _has_agent_in_earlier_events(agent.name, current_index, events)
    ]


def _has_agent_in_earlier_events(
    agent_name: str,
    current_index: int,
    events: list[Event],
) -> bool:
    """Check if an agent appears in any earlier RecallObservation."""
    return any(
        _is_recall_observation(event)
        and any(
            agent.name == agent_name
            for agent in cast(RecallObservation, event).playbook_knowledge
        )
        for event in events[:current_index]
    )


def _is_recall_observation(obj: object) -> bool:
    """Duck-type check for RecallObservation."""
    if isinstance(obj, RecallObservation):
        return True
    return type(obj).__name__ == 'RecallObservation'
