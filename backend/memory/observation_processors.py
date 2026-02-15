"""Observation processors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.enums import ActionType
from backend.core.logger import FORGE_logger as logger
from backend.core.message import ImageContent, Message, TextContent
from backend.events.observation import (
    BrowserOutputObservation,
    CmdOutputObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
    MCPObservation,
    Observation,
    UserRejectObservation,
)
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
    if isinstance(event, BrowserOutputObservation):
        return _handle_browser_output_observation(
            event,
            max_message_chars,
            vision_is_active,
            enable_som_visual_browsing,
        )
    if isinstance(event, ErrorObservation):
        return _handle_error_observation(event, max_message_chars)
    if isinstance(event, UserRejectObservation):
        return _handle_user_reject_observation(event, max_message_chars)
    if isinstance(event, FileDownloadObservation):
        return _handle_file_download_observation(event, max_message_chars)
    if isinstance(event, MCPObservation):
        return _handle_mcp_observation(event, max_message_chars)

    # Fallback for generic/simple observations
    return _handle_simple_observation(event, max_message_chars)


def _get_observation_content(obs: Observation) -> str:
    """Extract content string from observation."""
    if hasattr(obs, "content") and isinstance(obs.content, str):
        return obs.content
    if hasattr(obs, "message") and isinstance(obs.message, str):
        return obs.message
    return str(obs)


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


def _handle_file_read_observation(
    obs: FileReadObservation, max_message_chars: int | None
) -> Message:
    return Message(
        role="user", content=[TextContent(text=obs.content)]
    )  # Content already formatted by read action


def _handle_file_edit_observation(
    obs: FileEditObservation, max_message_chars: int | None
) -> Message:
    content_str = str(obs)
    text = truncate_content(content_str, max_message_chars)
    return Message(role="user", content=[TextContent(text=text)])


def _handle_cmd_output_observation(
    obs: CmdOutputObservation, max_message_chars: int | None
) -> Message:
    if obs.tool_call_metadata is None:
        text = truncate_content(
            f"\nObserved result of command executed by user:\n{obs.to_agent_observation()}",
            max_message_chars,
        )
    else:
        text = truncate_content(obs.to_agent_observation(), max_message_chars)
    return Message(role="user", content=[TextContent(text=text)])


def _handle_browser_output_observation(
    obs: BrowserOutputObservation,
    max_message_chars: int | None,
    vision_is_active: bool,
    enable_som_visual_browsing: bool,
) -> Message:
    content: list[TextContent | ImageContent] = [TextContent(text=obs.content)]

    if (
        obs.trigger_by_action == ActionType.BROWSE_INTERACTIVE
        and enable_som_visual_browsing
    ):
        _add_browser_visual_content(obs, content, vision_is_active)

    return Message(role="user", content=content)


def _add_browser_visual_content(
    obs: BrowserOutputObservation,
    content: list[TextContent | ImageContent],
    vision_is_active: bool,
) -> None:
    """Add visual content to browser observation message."""
    if vision_is_active:
        first_item = content[0]
        if isinstance(first_item, TextContent):
            first_item.text += (
                "Image: Current webpage screenshot (Note that only visible portion of webpage is present "
                "in the screenshot. However, the Accessibility tree contains information from the entire webpage.)\n"
            )

    image_url, image_type = _extract_browser_image(obs)

    if _is_valid_image_url(image_url):
        assert image_url is not None
        content.append(ImageContent(image_urls=[image_url]))
        logger.debug("Adding %s for browsing", image_type)
    elif vision_is_active:
        _add_browser_image_fallback(content, image_url, image_type)


def _extract_browser_image(
    obs: BrowserOutputObservation,
) -> tuple[str | None, str | None]:
    """Extract image URL and type from browser observation."""
    if obs.set_of_marks is not None and len(obs.set_of_marks) > 0:
        return obs.set_of_marks, "set of marks"
    if obs.screenshot is not None and len(obs.screenshot) > 0:
        return obs.screenshot, "screenshot"
    return None, None


def _is_valid_image_url(url: str | None) -> bool:
    """Check if an image URL is valid and non-empty."""
    if not url:
        return False
    return isinstance(url, str) and bool(url.strip())


def _add_browser_image_fallback(
    content: list[TextContent | ImageContent],
    image_url: str | None,
    image_type: str | None,
) -> None:
    """Add fallback message when image is unavailable."""
    first_item = content[0]
    if isinstance(first_item, TextContent):
        if image_url:
            logger.warning(
                "Invalid image URL format for %s: %s...",
                image_type,
                str(image_url)[:50],
            )
            first_item.text += (
                f"\n\nNote: The {image_type} for this webpage was invalid or empty and has been filtered. "
                "The agent should use alternative methods to access visual information about the webpage."
            )
        else:
            logger.debug("Vision enabled for browsing, but no valid image available")
            first_item.text += (
                "\n\nNote: No visual information (screenshot or set of marks) is available for this webpage. "
                "The agent should rely on the text content above."
            )


def _handle_error_observation(
    obs: ErrorObservation, max_message_chars: int | None
) -> Message:
    return _handle_simple_observation(
        obs,
        max_message_chars,
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
    text = truncate_content(obs.content, max_message_chars)
    return Message(role="user", content=[TextContent(text=text)])
