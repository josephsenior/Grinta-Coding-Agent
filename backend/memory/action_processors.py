"""Action processors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from backend.core.logger import forge_logger as logger
from backend.core.message import (
    ImageContent,
    Message,
    TextContent,
    ToolCall,
)
from backend.events.action import (
    Action,
    AgentThinkAction,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    MessageAction,
    PlaybookFinishAction,
    TaskTrackingAction,
)
from backend.events.action.agent import (
    ClarificationRequestAction,
    EscalateToHumanAction,
    ProposalAction,
    UncertaintyAction,
)
from backend.events.action.mcp import MCPAction

_META_COGNITION_ACTION_TYPES = (
    ClarificationRequestAction,
    ProposalAction,
    UncertaintyAction,
    EscalateToHumanAction,
)
from backend.events.action.message import SystemMessageAction
from backend.events.event import EventSource
from backend.events.model_response_lite import ModelResponseLite

if TYPE_CHECKING:
    pass


def convert_action_to_messages(
    action: Action,
    pending_tool_call_action_messages: dict[str, Message],
    vision_is_active: bool = False,
) -> list[Message]:
    """Converts an action into a message format that can be sent to the LLM.

    Args:
        action: The action to convert.
        pending_tool_call_action_messages: Dictionary mapping response IDs to messages.
        vision_is_active: Whether vision is active.

    Returns:
        list[Message]: Formatted message(s).
    """
    if _is_tool_based_action(action):
        return _handle_tool_based_action(action, pending_tool_call_action_messages)
    if isinstance(action, PlaybookFinishAction):
        return _handle_agent_finish_action(action)
    if isinstance(action, MessageAction):
        return _handle_message_action(action, vision_is_active)
    if isinstance(action, CmdRunAction):
        src = getattr(action, "source", None)
        if isinstance(src, EventSource):
            pass
        else:
            pass
        # Both user and agent cmd actions are handled similarly now?
        # In conversation_memory.py, both branches called _handle_user_cmd_action.
        return _handle_user_cmd_action(action)
    if isinstance(action, SystemMessageAction):
        return _handle_system_message_action(action)
    return []


def _is_tool_based_action(action: Action) -> bool:
    """Check if action is a tool-based action."""
    src = getattr(action, "source", None)
    if isinstance(src, EventSource):
        src_value = src.value
    else:
        src_value = src
    tool_action_classes = (
        AgentThinkAction,
        FileEditAction,
        FileReadAction,
        MCPAction,
        TaskTrackingAction,
        *_META_COGNITION_ACTION_TYPES,
    )
    if isinstance(action, tool_action_classes):
        return True
    return isinstance(action, CmdRunAction) and src_value == "agent"


def _handle_tool_based_action(
    action: Action,
    pending_tool_call_action_messages: dict[str, Message],
) -> list[Message]:
    """Handle tool-based actions in function calling mode."""
    if _should_emit_user_tool_request(action):
        return _build_user_tool_request_message(action)

    if isinstance(action, AgentThinkAction):
        return _build_think_action_message(action)

    if isinstance(action, _META_COGNITION_ACTION_TYPES):
        return _build_meta_cognition_message(action)

    tool_metadata = _require_tool_metadata(action)
    llm_response = _extract_llm_response(tool_metadata)
    if llm_response is None:
        return []

    assistant_msg = _first_choice_message(llm_response)
    if assistant_msg is None:
        return []

    role = _role_from_assistant_message(assistant_msg)
    content_items = _content_from_assistant_message(assistant_msg)
    response_id = getattr(llm_response, "id", None)
    if response_id is None:
        return []

    tool_calls_payload = _convert_tool_calls(getattr(assistant_msg, "tool_calls", None))
    pending_tool_call_action_messages[str(response_id)] = Message(
        role=role,
        content=content_items,
        tool_calls=tool_calls_payload,
    )
    return []


def _should_emit_user_tool_request(action: Action) -> bool:
    src_value = getattr(getattr(action, "source", None), "value", None) or getattr(
        action, "source", None
    )
    return src_value == "user" and getattr(action, "tool_call_metadata", None) is None


def _build_user_tool_request_message(action: Action) -> list[Message]:
    content: list[TextContent | ImageContent] = [
        TextContent(text=f"User requested to read file: {action!s}"),
    ]
    return [Message(role="user", content=content)]


def _build_think_action_message(action: Action) -> list[Message]:
    think_text = cast(str, getattr(action, "thought", "")) or ""
    think_content: list[TextContent | ImageContent] = [
        TextContent(text=f"🤔 {think_text}")
    ]
    return [Message(role="assistant", content=think_content)]


def _build_meta_cognition_message(action: Action) -> list[Message]:
    """Build a user-visible assistant message from a meta-cognition action."""
    msg_text = getattr(action, "message", "") or str(action)
    content: list[TextContent | ImageContent] = [TextContent(text=msg_text)]
    return [Message(role="assistant", content=content)]


def _require_tool_metadata(action: Action):
    tool_metadata = getattr(action, "tool_call_metadata", None)
    assert tool_metadata is not None, (
        f"Tool call metadata should NOT be None when function calling is enabled for agent actions. Action: {action!s}"
    )
    return tool_metadata


def _extract_llm_response(tool_metadata) -> ModelResponseLite | None:
    llm_response = _to_model_response_lite(tool_metadata.model_response)
    if llm_response is None or not llm_response.choices:
        return None
    return llm_response


def _to_model_response_lite(response: Any) -> ModelResponseLite | None:
    """Normalize SDK or dict responses into a ModelResponseLite."""
    if response is None:
        return None
    if isinstance(response, ModelResponseLite):
        return response
    try:
        return ModelResponseLite.from_sdk(response)
    except Exception:
        logger.debug(
            "Failed to normalize model response %s",
            type(response).__name__,
            exc_info=True,
        )
        return None


def _first_choice_message(llm_response: ModelResponseLite) -> Any | None:
    if not getattr(llm_response, "choices", None) or len(llm_response.choices) == 0:
        return None
    raw_choice = llm_response.choices[0]
    if not hasattr(raw_choice, "message"):
        return None
    return cast(Any, raw_choice).message


def _role_from_assistant_message(
    assistant_msg: Any,
) -> Literal["user", "system", "assistant", "tool"]:
    role_value = getattr(assistant_msg, "role", "assistant")
    if role_value not in {"user", "system", "assistant", "tool"}:
        role_value = "assistant"
    return cast(Literal["user", "system", "assistant", "tool"], role_value)


def _content_from_assistant_message(
    assistant_msg: Any,
) -> list[TextContent | ImageContent]:
    content_items: list[TextContent | ImageContent] = []
    assistant_content = getattr(assistant_msg, "content", None)
    if isinstance(assistant_content, str):
        stripped = assistant_content.strip()
        if stripped:
            content_items.append(TextContent(text=stripped))
    elif assistant_content not in (None, ""):
        text_value = str(assistant_content).strip()
        if text_value:
            content_items.append(TextContent(text=text_value))
    return content_items


def _convert_tool_calls(raw_tool_calls: Any) -> list[ToolCall] | None:
    """Convert SDK-specific tool call payloads into dicts accepted by Message."""
    if not raw_tool_calls:
        return None
    normalized: list[ToolCall] = []
    for idx, call in enumerate(raw_tool_calls):
        call_dict: dict[str, Any]
        if isinstance(call, dict):
            call_dict = dict(call)
        elif hasattr(call, "model_dump"):
            call_dict = cast(dict[str, Any], call.model_dump())
        else:
            call_dict = {
                "id": getattr(call, "id", None),
                "type": getattr(call, "type", "function"),
                "function": getattr(call, "function", None),
                "arguments": getattr(call, "arguments", None),
                "name": getattr(call, "name", None),
            }

        _ensure_tool_call_function(call_dict, call, idx)
        if not call_dict.get("id"):
            call_dict["id"] = call_dict.get("tool_call_id") or f"tool_call_{idx}"
        call_dict.setdefault("type", getattr(call, "type", "function"))
        normalized.append(ToolCall.model_validate(call_dict))
    return normalized


def _ensure_tool_call_function(
    call_dict: dict[str, Any], source: Any, idx: int
) -> None:
    """Ensure tool call payload includes a proper function dict."""
    function_payload = call_dict.get("function")
    fallback_name = (
        call_dict.get("name")
        or getattr(source, "function_name", None)
        or getattr(source, "name", None)
        or f"tool_call_{idx}"
    )
    fallback_arguments = (
        call_dict.get("arguments") or getattr(source, "arguments", None) or "{}"
    )

    if not function_payload:
        function_payload = {
            "name": fallback_name,
            "arguments": fallback_arguments,
        }
    elif isinstance(function_payload, dict):
        function_payload.setdefault("name", fallback_name)
        function_payload.setdefault("arguments", fallback_arguments)
    else:
        function_payload = {
            "name": getattr(function_payload, "name", fallback_name),
            "arguments": getattr(function_payload, "arguments", fallback_arguments),
        }

    call_dict["function"] = function_payload


def _handle_agent_finish_action(action: PlaybookFinishAction) -> list[Message]:
    """Handle PlaybookFinishAction by converting thought/conclusion to message."""
    role = _role_from_source(getattr(action, "source", None))
    _merge_tool_metadata_thought(action)
    content_items: list[TextContent | ImageContent] = [
        TextContent(text=action.thought or "")
    ]
    return [Message(role=role, content=content_items)]


def _role_from_source(
    source: EventSource | str | None,
) -> Literal["user", "system", "assistant", "tool"]:
    src_value = source.value if isinstance(source, EventSource) else source
    role_value = "user" if src_value == "user" else "assistant"
    return cast(Literal["user", "system", "assistant", "tool"], role_value)


def _merge_tool_metadata_thought(action: PlaybookFinishAction) -> None:
    tool_metadata = action.tool_call_metadata
    if tool_metadata is None:
        return
    response = _to_model_response_lite(tool_metadata.model_response)
    if response is None or not response.choices:
        setattr(action, "tool_call_metadata", None)
        return
    choice = response.choices[0]
    if not hasattr(choice, "message"):
        setattr(action, "tool_call_metadata", None)
        return
    assistant_msg = cast(Any, choice).message
    content = getattr(assistant_msg, "content", "") or ""
    if action.thought:
        if action.thought != content and content:
            action.thought += "\n" + content
    else:
        action.thought = content
    setattr(action, "tool_call_metadata", None)


def _handle_message_action(
    action: MessageAction, vision_is_active: bool
) -> list[Message]:
    """Handle MessageAction with optional image content."""
    src = getattr(action, "source", None)
    if isinstance(src, EventSource):
        src_value = src.value
    else:
        src_value = src
    role_value = "user" if src_value == "user" else "assistant"
    if role_value not in {"user", "system", "assistant", "tool"}:
        role_value = "assistant"
    role = cast(Literal["user", "system", "assistant", "tool"], role_value)
    content: list[TextContent | ImageContent] = [TextContent(text=action.content or "")]

    if action.image_urls:
        if role == "user":
            for idx, url in enumerate(action.image_urls):
                if vision_is_active:
                    content.append(TextContent(text=f"Image {idx + 1}:"))
                content.append(ImageContent(image_urls=[url]))
        else:
            content.append(ImageContent(image_urls=action.image_urls))

    if role not in ("user", "system", "assistant", "tool"):
        msg = f"Invalid role: {role}"
        raise ValueError(msg)
    return [Message(role=role, content=content)]


def _handle_user_cmd_action(action: CmdRunAction) -> list[Message]:
    """Handle CmdRunAction."""
    content_items: list[TextContent | ImageContent] = [
        TextContent(text=f"User executed the command:\n{action.command}"),
    ]
    return [Message(role="user", content=content_items)]


def _handle_system_message_action(action: SystemMessageAction) -> list[Message]:
    """Handle SystemMessageAction."""
    content_items: list[TextContent | ImageContent] = [TextContent(text=action.content)]
    return [Message(role="system", content=content_items, tool_calls=None)]
