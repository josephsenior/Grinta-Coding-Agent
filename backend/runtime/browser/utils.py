"""Helper functions for runtime browser interactions and observations."""

from __future__ import annotations

import base64
import contextlib
import datetime
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, assert_never

from browsergym.utils.obs import flatten_axtree_to_str  # type: ignore[import-untyped]
from PIL import Image

from backend.core.exceptions import BrowserUnavailableException
from backend.core.schemas import ActionType
from backend.events.action import BrowseInteractiveAction, BrowseURLAction
from backend.events.observation import BrowserOutputObservation
from backend.runtime.browser.base64 import png_base64_url_to_image
from backend.utils.async_utils import call_sync_from_async

if TYPE_CHECKING:
    from backend.runtime.browser.browser_env import BrowserEnv


def _ensure_str(value: Any, default: str = "") -> str:
    """Return a string representation, falling back to default for None."""
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


def _ensure_int(value: Any, default: int = 0) -> int:
    """Return an integer representation, falling back to default for invalid values."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ensure_str_list(value: Any) -> list[str]:
    """Normalize a list of arbitrary values into a list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _ensure_dict(value: Any) -> dict[str, Any]:
    """Ensure the provided value is a dictionary."""
    if isinstance(value, dict):
        return value
    return {}


def get_axtree_str(
    axtree_object: dict[str, Any],
    extra_element_properties: dict[str, Any],
    filter_visible_only: bool = False,
) -> str:
    """Convert accessibility tree object to string representation.

    Flattens the accessibility tree with specified properties and filters.

    Args:
        axtree_object: Accessibility tree object from browser
        extra_element_properties: Additional properties to include
        filter_visible_only: Whether to filter to visible elements only

    Returns:
        String representation of the accessibility tree

    """
    cur_axtree_txt = flatten_axtree_to_str(
        axtree_object,
        extra_properties=extra_element_properties,
        with_clickable=True,
        skip_generic=False,
        filter_visible_only=filter_visible_only,
    )
    return str(cur_axtree_txt)


def get_agent_obs_text(obs: BrowserOutputObservation) -> str:
    """Get a concise text that will be shown to the agent."""
    if obs.trigger_by_action == ActionType.BROWSE_INTERACTIVE:
        text = f"[Current URL: {obs.url}]\n"
        text += f"[Focused element bid: {obs.focused_element_bid}]\n"
        if obs.screenshot_path:
            text += f"[Screenshot saved to: {obs.screenshot_path}]\n"
        text += "\n"
        if obs.error:
            text += f"================ BEGIN error message ===============\nThe following error occurred when executing the last action:\n{
                obs.last_browser_action_error
            }\n================ END error message ===============\n"
        else:
            text += "[Action executed successfully.]\n"
        try:
            cur_axtree_txt = get_axtree_str(
                obs.axtree_object,
                obs.extra_element_properties,
                filter_visible_only=obs.filter_visible_only,
            )
            if not obs.filter_visible_only:
                text += f"Accessibility tree of the COMPLETE webpage:\nNote: [bid] is the unique alpha-numeric identifier at the beginning of lines for each element in the AXTree. Always use bid to refer to elements in your actions.\n============== BEGIN accessibility tree ==============\n{cur_axtree_txt}\n============== END accessibility tree ==============\n"
            else:
                text += f"Accessibility tree of the VISIBLE portion of the webpage (accessibility tree of complete webpage is too large and you may need to scroll to view remaining portion of the webpage):\nNote: [bid] is the unique alpha-numeric identifier at the beginning of lines for each element in the AXTree. Always use bid to refer to elements in your actions.\n============== BEGIN accessibility tree ==============\n{cur_axtree_txt}\n============== END accessibility tree ==============\n"
        except Exception as e:
            text += f"\n[Error encountered when processing the accessibility tree: {e}]"
        return text
    if obs.trigger_by_action == ActionType.BROWSE:
        text = f"[Current URL: {obs.url}]\n"
        if obs.error:
            text += f"================ BEGIN error message ===============\nThe following error occurred when trying to visit the URL:\n{
                obs.last_browser_action_error
            }\n================ END error message ===============\n"
        text += "============== BEGIN webpage content ==============\n"
        text += obs.content
        text += "\n============== END webpage content ==============\n"
        return text
    msg = f"Invalid trigger_by_action: {obs.trigger_by_action}"
    raise ValueError(msg)


async def browse(
    action: BrowseURLAction | BrowseInteractiveAction,
    browser: BrowserEnv | None,
    workspace_dir: str | None = None,
) -> BrowserOutputObservation:
    """Execute a browser action and return observation.

    Reduced complexity: 13 → 5 by extracting screenshot and observation creation logic.
    """
    if browser is None:
        raise BrowserUnavailableException

    # Prepare browser action string
    action_str, asked_url = _prepare_browser_action(action)

    try:
        # Execute browser action
        obs = await call_sync_from_async(browser.step, action_str)

        # Save screenshot if needed
        screenshot_path = await _save_screenshot_if_needed(obs, workspace_dir)

        # Create observation from browser response
        observation = _create_browser_observation(obs, screenshot_path, action)

        # Strip DOM data if not needed
        if not action.return_axtree:
            _strip_dom_data(observation)

        return observation

    except Exception as e:
        return _create_error_observation(e, asked_url, action)


def _prepare_browser_action(
    action: BrowseURLAction | BrowseInteractiveAction,
) -> tuple[str, str]:
    """Prepare the browser action string based on action type.

    Returns: (action_string, asked_url)
    """
    if isinstance(action, BrowseURLAction):
        asked_url = action.url
        if not asked_url.startswith("http"):
            asked_url = os.path.abspath(os.curdir) + action.url
        action_str = f'goto("{asked_url}")'
        return (action_str, asked_url)
    if isinstance(action, BrowseInteractiveAction):
        return (action.browser_actions, "")
    assert_never(action)


async def _save_screenshot_if_needed(
    obs: dict[str, Any], workspace_dir: str | None
) -> str | None:
    """Save screenshot to workspace if available.

    Returns: Path to saved screenshot or None.
    """
    if workspace_dir is None or not obs.get("screenshot"):
        return None

    # Prepare screenshot directory and path
    screenshots_dir = Path(workspace_dir) / ".browser_screenshots"
    screenshots_dir.mkdir(exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    screenshot_filename = f"screenshot_{timestamp}.png"
    screenshot_path = str(screenshots_dir / screenshot_filename)

    # Extract base64 data
    base64_data = _ensure_str(obs.get("screenshot", ""))
    if "," in base64_data:
        base64_data = base64_data.split(",")[1]

    # Save screenshot with fallback
    try:
        image_data = base64.b64decode(base64_data)
        with open(screenshot_path, "wb") as f:
            f.write(image_data)
        Image.open(screenshot_path).verify()
    except Exception:
        # Fallback: use PNG converter
        image = png_base64_url_to_image(_ensure_str(obs.get("screenshot")))
        image.save(screenshot_path, format="PNG", optimize=True)

    return screenshot_path


def _create_browser_observation(
    obs: dict[str, Any],
    screenshot_path: str | None,
    action: BrowseURLAction | BrowseInteractiveAction,
) -> BrowserOutputObservation:
    """Create BrowserOutputObservation from browser response."""
    observation = BrowserOutputObservation(
        content=_ensure_str(obs.get("text_content", "")),
        url=_ensure_str(obs.get("url", "")),
        screenshot=_ensure_str(obs.get("screenshot", "")),
        screenshot_path=screenshot_path,
        set_of_marks=_ensure_str(obs.get("set_of_marks", "")),
        goal_image_urls=_ensure_str_list(obs.get("image_content", [])),
        open_pages_urls=_ensure_str_list(obs.get("open_pages_urls", [])),
        active_page_index=_ensure_int(obs.get("active_page_index", -1), -1),
        axtree_object=_ensure_dict(obs.get("axtree_object")),
        extra_element_properties=_ensure_dict(obs.get("extra_element_properties")),
        focused_element_bid=_ensure_str(obs.get("focused_element_bid", "")),
        last_browser_action=_ensure_str(obs.get("last_action", "")),
        last_browser_action_error=_ensure_str(obs.get("last_action_error", "")),
        error=bool(obs.get("last_action_error", "")),
        trigger_by_action=action.action,
    )

    # Format content for agent
    observation.content = get_agent_obs_text(observation)

    return observation


def _strip_dom_data(observation: BrowserOutputObservation) -> None:
    """Remove DOM data from observation if not needed."""
    observation.dom_object = {}
    observation.axtree_object = {}
    observation.extra_element_properties = {}


def _create_error_observation(
    error: Exception,
    asked_url: str,
    action: BrowseURLAction | BrowseInteractiveAction,
) -> BrowserOutputObservation:
    """Create an error observation when browser action fails."""
    error_message = str(error)
    error_url = asked_url if action.action == ActionType.BROWSE else ""

    observation = BrowserOutputObservation(
        content=error_message,
        screenshot="",
        screenshot_path=None,
        error=True,
        last_browser_action_error=error_message,
        url=error_url,
        trigger_by_action=action.action,
    )

    # Try to format content, but don't fail if it doesn't work
    with contextlib.suppress(Exception):
        observation.content = get_agent_obs_text(observation)

    return observation
