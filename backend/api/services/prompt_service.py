"""Prompt generation service for conversation context recall.

Extracted from ``manage_conversations.py`` to keep route handlers thin.
Contains template rendering, LLM prompt generation, and contextual event
retrieval for the ``remember-prompt`` endpoint.
"""

from __future__ import annotations

import os
import re
from typing import Any

from backend.core.config.llm_config import LLMConfig
from backend.events.action import ChangeAgentStateAction, NullAction
from backend.events.event_filter import EventFilter
from backend.events.event_store import EventStore
from backend.events.observation import AgentStateChangedObservation, NullObservation
from backend.api.services.event_query_service import get_contextual_events_text
from backend.api.app_accessors import get_conversation_manager_impl


def get_contextual_events(event_store: EventStore, event_id: int) -> str:
    """Get contextual events around a specific event ID.

    Args:
        event_store: The event store to search in.
        event_id: The event ID to get context around.

    Returns:
        Stringified contextual events.
    """
    context_size = 4
    agent_event_filter = EventFilter(
        exclude_hidden=True,
        exclude_types=(
            NullAction,
            NullObservation,
            ChangeAgentStateAction,
            AgentStateChangedObservation,
        ),
    )
    return get_contextual_events_text(
        event_store=event_store,
        event_id=event_id,
        event_filter=agent_event_filter,
        context_size=context_size,
    )


def generate_prompt_template(events: str) -> str:
    """Generate a prompt template from events using Jinja2.

    Args:
        events: The events string to include in the template.

    Returns:
        The rendered prompt template.
    """
    from jinja2 import Environment, FileSystemLoader

    backend_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    search_paths = [
        os.path.join(backend_root, "instruction", "prompts"),
        os.path.join(backend_root, "playbook_engine", "prompts"),
    ]

    # nosec B701 - Template rendering for prompts (not HTML), autoescape enabled
    env = Environment(
        loader=FileSystemLoader(search_paths),
        autoescape=True,
    )
    template = env.get_template("generate_remember_prompt.j2")
    return template.render(events=events)


async def generate_prompt(
    llm_config: LLMConfig, prompt_template: str, conversation_id: str
) -> str:
    """Generate a prompt using LLM configuration and template.

    Args:
        llm_config: LLM configuration settings.
        prompt_template: The template to use for prompt generation.
        conversation_id: The conversation ID for context.

    Returns:
        The generated prompt.

    Raises:
        RuntimeError: If conversation manager is unavailable.
        ValueError: If no valid prompt is found in the LLM response.
    """
    messages = [
        {"role": "system", "content": prompt_template},
        {
            "role": "user",
            "content": "Please generate a prompt for the AI to update the special file based on the events provided.",
        },
    ]
    manager_impl = get_conversation_manager_impl()
    if manager_impl is None:
        raise RuntimeError("Conversation manager implementation unavailable")
    raw_prompt = await manager_impl.request_llm_completion(
        "remember_prompt",
        conversation_id,
        llm_config,
        messages,
    )
    if prompt := re.search(
        "<update_prompt>(.*?)</update_prompt>", raw_prompt, re.DOTALL
    ):
        return prompt[1].strip()
    msg = "No valid prompt found in the response."
    raise ValueError(msg)


# ---------------------------------------------------------------------------
# Facade: remember-prompt generation
# ---------------------------------------------------------------------------


async def build_remember_prompt(
    conversation_id: str,
    event_id: int,
    user_id: str | None,
    user_settings_store: Any,
    file_store: Any,
) -> str:
    """Orchestrate the full remember-prompt pipeline.

    Encapsulates EventStore creation, settings loading, LLM config
    construction, and prompt generation — logic previously inlined in
    the ``get_prompt`` route handler.

    Returns:
        The generated remember-prompt string.

    Raises:
        ValueError: If settings are missing or prompt generation fails.
    """
    event_store = EventStore(
        sid=conversation_id,
        file_store=file_store,
        user_id=user_id,
    )
    stringified_events = get_contextual_events(event_store, event_id)

    settings = await user_settings_store.load()
    if settings is None:
        raise ValueError("Settings not found")

    extra_config = {}
    if settings.llm_model:
        extra_config["model"] = settings.llm_model
    if settings.llm_api_key:
        extra_config["api_key"] = settings.llm_api_key
    if settings.llm_base_url:
        extra_config["base_url"] = settings.llm_base_url

    llm_config = LLMConfig(**extra_config)
    prompt_template = generate_prompt_template(stringified_events)
    return await generate_prompt(llm_config, prompt_template, conversation_id)
