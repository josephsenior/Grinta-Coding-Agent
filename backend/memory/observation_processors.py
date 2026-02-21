"""Observation processors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.message import Message, TextContent
from backend.events.observation import (
    CmdOutputObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
    MCPObservation,
    Observation,
    UserRejectObservation,
)
from backend.events.observation.agent import AgentCondensationObservation
from backend.events.serialization.event import truncate_content

if TYPE_CHECKING:
    pass


def convert_observation_to_message(
    event: Observation,
    max_message_chars: int | None = None,
    vision_is_active: bool = False,
    enable_som_visual_browsing: bool = False,
) -> Message:
    """Convert an Observation event into a Message for the LLM.

    Args:
        event: The observation event to convert
        max_message_chars: Maximum characters for text content
        vision_is_active: Whether vision is enabled in the LLM
        enable_som_visual_browsing: Whether SOM (Set of Marks) visual browsing is enabled

    Returns:
        Message: A formatted message ready for the LLM

    """
    if isinstance(event, FileReadObservation):
        return _handle_file_read_observation(event, max_message_chars)
    if isinstance(event, FileEditObservation):
        return _handle_file_edit_observation(event, max_message_chars)
    if isinstance(event, CmdOutputObservation):
        return _handle_cmd_output_observation(event, max_message_chars)
    if isinstance(event, ErrorObservation):
        return _handle_error_observation(event, max_message_chars)
    if isinstance(event, UserRejectObservation):
        return _handle_user_reject_observation(event, max_message_chars)
    if isinstance(event, FileDownloadObservation):
        return _handle_file_download_observation(event, max_message_chars)
    if isinstance(event, MCPObservation):
        return _handle_mcp_observation(event, max_message_chars)
    if isinstance(event, AgentCondensationObservation):
        return _handle_condensation_observation(event, max_message_chars)

    # Fallback for generic/simple observations
    return _handle_simple_observation(event, max_message_chars)


def _get_observation_content(obs: Observation) -> str:
    """Extract content string from observation."""
    if hasattr(obs, "content") and isinstance(obs.content, str):
        return obs.content
    if hasattr(obs, "message") and isinstance(obs.message, str):
        return obs.message
    return str(obs)


def _is_valid_image_url(url: object) -> bool:
    """Return True when the provided value looks like a usable image reference.

    This is intentionally permissive: URLs, data-URLs, and local/relative paths
    are all treated as valid as long as they are non-empty strings.
    """
    if not isinstance(url, str):
        return False
    return bool(url.strip())


def _handle_simple_observation(
    obs: Observation,
    max_message_chars: int | None,
    prefix: str = "",
    suffix: str = "",
) -> Message:
    """Handle simple/generic observations."""
    content_str = _get_observation_content(obs)
    text = truncate_content(content_str, max_message_chars)
    if prefix:
        text = prefix + text
    if suffix:
        text += suffix
    return Message(role="user", content=[TextContent(text=text)])


_CONDENSATION_BANNER = (
    "\u26a1 CONTEXT CONDENSED — older conversation events were replaced by the summary below.\n"
    + "─" * 60 + "\n"
)

_POST_CONDENSATION_RECOVERY = (
    "\n" + "─" * 60 + "\n"
    "⚠️ POST-CONDENSATION RECOVERY PROTOCOL:\n"
    "Your context was just condensed. Prior tool outputs and file contents are gone.\n"
    "Before continuing, you MUST:\n"
    "1. recall(key=\"all\") — retrieve your scratchpad to restore decisions and findings\n"
    "2. Re-read any files you were actively editing (use view command)\n"
    "3. Review your task tracker (task_tracker view) to confirm current progress\n"
    "4. Use think() to re-orient: what was I doing? what's next?\n"
    "Do NOT proceed with edits until you have re-established context.\n"
)


def _handle_condensation_observation(
    obs: AgentCondensationObservation, max_message_chars: int | None
) -> Message:
    """Handle AgentCondensationObservation with an explicit visibility banner."""
    summary = obs.content or "(no summary provided)"
    text = truncate_content(
        _CONDENSATION_BANNER + summary + _POST_CONDENSATION_RECOVERY,
        max_message_chars,
    )
    return Message(role="user", content=[TextContent(text=text)])


def _handle_file_read_observation(
    obs: FileReadObservation, max_message_chars: int | None
) -> Message:
    path = getattr(obs, "path", "unknown")
    text = truncate_content(obs.content, max_message_chars, strategy="head_heavy")
    text = f"[FILE_READ path={path}]\n{text}"
    return Message(
        role="user", content=[TextContent(text=text)]
    )


def _handle_file_edit_observation(
    obs: FileEditObservation, max_message_chars: int | None
) -> Message:
    content_str = str(obs)
    text = truncate_content(content_str, max_message_chars, strategy="balanced")
    path = getattr(obs, "path", "unknown")
    text = f"[FILE_EDIT path={path}]\n{text}"
    return Message(role="user", content=[TextContent(text=text)])


_ERROR_CLASSIFIERS: list[tuple[str, list[str]]] = [
    ("PYTHON_IMPORT_ERROR", ["ModuleNotFoundError", "ImportError", "No module named"]),
    ("PYTHON_SYNTAX_ERROR", ["SyntaxError:", "IndentationError:", "TabError:"]),
    ("PYTHON_TYPE_ERROR", ["TypeError:"]),
    ("PYTHON_NAME_ERROR", ["NameError:", "is not defined"]),
    ("PYTHON_ATTRIBUTE_ERROR", ["AttributeError:", "has no attribute"]),
    ("PYTHON_VALUE_ERROR", ["ValueError:"]),
    ("PYTHON_KEY_ERROR", ["KeyError:"]),
    ("PYTHON_INDEX_ERROR", ["IndexError:"]),
    ("FILE_NOT_FOUND", ["FileNotFoundError", "No such file or directory", "ENOENT"]),
    ("PERMISSION_DENIED", ["PermissionError", "Permission denied", "EACCES"]),
    ("TIMEOUT_ERROR", ["TimeoutError", "timed out", "ETIMEDOUT"]),
    ("CONNECTION_ERROR", ["ConnectionError", "ConnectionRefused", "ECONNREFUSED"]),
    ("RUNTIME_ERROR", ["RuntimeError:"]),
    ("ASSERTION_ERROR", ["AssertionError:", "assert "]),
    ("TEST_FAILURE", ["FAILED", "failures=", "tests failed", "ERRORS"]),
    ("COMMAND_NOT_FOUND", ["command not found", "not recognized as"]),
    ("NPM_ERROR", ["npm ERR!", "npm error"]),
    ("GIT_ERROR", ["fatal:", "error: failed to"]),
    ("MEMORY_ERROR", ["MemoryError", "OutOfMemoryError", "OOM"]),
    ("DISK_ERROR", ["No space left on device", "ENOSPC"]),
]


def _classify_cmd_error(content: str) -> str | None:
    """Classify a command output error by scanning content for known patterns.

    Returns the error type string (e.g. 'PYTHON_IMPORT_ERROR') or None.
    """
    for error_type, patterns in _ERROR_CLASSIFIERS:
        for pattern in patterns:
            if pattern in content:
                return error_type
    return None


def _handle_cmd_output_observation(
    obs: CmdOutputObservation, max_message_chars: int | None
) -> Message:
    exit_code = getattr(obs, "exit_code", None)
    exit_tag = f" exit={exit_code}" if exit_code is not None else ""

    error_type_tag = ""
    if exit_code is not None and exit_code != 0:
        classified = _classify_cmd_error(obs.content)
        if classified:
            error_type_tag = f" error_type={classified}"

    tag = f"[CMD_OUTPUT{exit_tag}{error_type_tag}]"
    # Use tail_heavy for errors (traceback at end), balanced otherwise
    cmd_strategy = "tail_heavy" if (exit_code is not None and exit_code != 0) else "balanced"
    if obs.tool_call_metadata is None:
        text = truncate_content(
            f"{tag}\nObserved result of command executed by user:\n{obs.to_agent_observation()}",
            max_message_chars,
            strategy=cmd_strategy,
        )
    else:
        text = truncate_content(f"{tag}\n{obs.to_agent_observation()}", max_message_chars, strategy=cmd_strategy)
    return Message(role="user", content=[TextContent(text=text)])


def _handle_error_observation(
    obs: ErrorObservation, max_message_chars: int | None
) -> Message:
    error_id = getattr(obs, "error_id", "UNKNOWN")
    return _handle_simple_observation(
        obs,
        max_message_chars,
        prefix=f"[ERROR type={error_id}]\n",
        suffix="\n[Error occurred in processing last action]",
    )


def _handle_user_reject_observation(
    obs: UserRejectObservation, max_message_chars: int | None
) -> Message:
    return _handle_simple_observation(
        obs,
        max_message_chars,
        prefix="OBSERVATION:\n",
        suffix="\n[Last action has been rejected by the user]",
    )


def _handle_file_download_observation(
    obs: FileDownloadObservation, max_message_chars: int | None
) -> Message:
    return _handle_simple_observation(obs, max_message_chars)


def _handle_mcp_observation(
    obs: MCPObservation, max_message_chars: int | None
) -> Message:
    tool_name = getattr(obs, "name", "unknown")
    text = truncate_content(f"[MCP_RESULT tool={tool_name}]\n{obs.content}", max_message_chars, strategy="balanced")
    return Message(role="user", content=[TextContent(text=text)])
