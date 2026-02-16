"""Tests for backend.runtime.browser.utils — browser helper functions."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from backend.core.exceptions import BrowserUnavailableException
from backend.core.schemas import ActionType
from backend.events.action import BrowseInteractiveAction, BrowseURLAction
from backend.events.observation import BrowserOutputObservation
from backend.runtime.browser.utils import (
    _create_browser_observation,
    _create_error_observation,
    _ensure_dict,
    _ensure_int,
    _ensure_str,
    _ensure_str_list,
    _prepare_browser_action,
    _save_screenshot_if_needed,
    _strip_dom_data,
    browse,
    get_agent_obs_text,
    get_axtree_str,
)


class TestEnsureStr:
    """Tests for _ensure_str helper."""

    def test_returns_string_unchanged(self):
        """Test returns string as-is."""
        assert _ensure_str("hello") == "hello"

    def test_converts_none_to_default(self):
        """Test converts None to empty string by default."""
        assert _ensure_str(None) == ""

    def test_converts_none_to_custom_default(self):
        """Test converts None to custom default."""
        assert _ensure_str(None, "N/A") == "N/A"

    def test_converts_int_to_string(self):
        """Test converts integers to strings."""
        assert _ensure_str(42) == "42"

    def test_converts_float_to_string(self):
        """Test converts floats to strings."""
        assert _ensure_str(3.14) == "3.14"

    def test_converts_bool_to_string(self):
        """Test converts booleans to strings."""
        assert _ensure_str(True) == "True"
        assert _ensure_str(False) == "False"


class TestEnsureInt:
    """Tests for _ensure_int helper."""

    def test_returns_int_unchanged(self):
        """Test returns integer as-is."""
        assert _ensure_int(42) == 42

    def test_converts_string_to_int(self):
        """Test converts numeric string to integer."""
        assert _ensure_int("123") == 123

    def test_converts_float_to_int(self):
        """Test converts float to integer."""
        assert _ensure_int(3.7) == 3

    def test_returns_default_for_none(self):
        """Test returns 0 for None by default."""
        assert _ensure_int(None) == 0

    def test_returns_custom_default_for_none(self):
        """Test returns custom default for None."""
        assert _ensure_int(None, -1) == -1

    def test_returns_default_for_invalid_string(self):
        """Test returns default for non-numeric string."""
        assert _ensure_int("not a number") == 0

    def test_returns_default_for_list(self):
        """Test returns default for list."""
        assert _ensure_int([1, 2, 3], 99) == 99


class TestEnsureStrList:
    """Tests for _ensure_str_list helper."""

    def test_converts_list_of_strings(self):
        """Test returns list of strings unchanged."""
        result = _ensure_str_list(["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_converts_list_of_ints_to_strings(self):
        """Test converts list of integers to strings."""
        result = _ensure_str_list([1, 2, 3])
        assert result == ["1", "2", "3"]

    def test_converts_mixed_list_to_strings(self):
        """Test converts mixed list to strings."""
        result = _ensure_str_list([1, "two", 3.0, None])
        assert result == ["1", "two", "3.0", "None"]

    def test_returns_empty_list_for_non_list(self):
        """Test returns empty list for non-list input."""
        assert _ensure_str_list("not a list") == []
        assert _ensure_str_list(42) == []
        assert _ensure_str_list(None) == []


class TestEnsureDict:
    """Tests for _ensure_dict helper."""

    def test_returns_dict_unchanged(self):
        """Test returns dictionary as-is."""
        d = {"key": "value"}
        assert _ensure_dict(d) == d

    def test_returns_empty_dict_for_non_dict(self):
        """Test returns empty dict for non-dict input."""
        assert _ensure_dict("not a dict") == {}
        assert _ensure_dict(42) == {}
        assert _ensure_dict(None) == {}
        assert _ensure_dict([1, 2, 3]) == {}


class TestGetAxtreeStr:
    """Tests for get_axtree_str function."""

    @patch("backend.runtime.browser.utils.flatten_axtree_to_str")
    def test_calls_flatten_with_correct_args(self, mock_flatten):
        """Test calls flatten_axtree_to_str with correct arguments."""
        mock_flatten.return_value = "flattened tree"

        axtree = {"nodes": [{"id": 1}]}
        extra_props = {"visible": True}

        result = get_axtree_str(axtree, extra_props, filter_visible_only=True)

        mock_flatten.assert_called_once_with(
            axtree,
            extra_properties=extra_props,
            with_clickable=True,
            skip_generic=False,
            filter_visible_only=True,
        )
        assert result == "flattened tree"

    @patch("backend.runtime.browser.utils.flatten_axtree_to_str")
    def test_defaults_to_all_elements(self, mock_flatten):
        """Test filter_visible_only defaults to False."""
        mock_flatten.return_value = "all elements"

        result = get_axtree_str({}, {})

        assert mock_flatten.call_args[1]["filter_visible_only"] is False
        assert result == "all elements"


class TestGetAgentObsText:
    """Tests for get_agent_obs_text function."""

    def test_browse_interactive_success(self):
        """Test formats BROWSE_INTERACTIVE observation successfully."""
        obs = BrowserOutputObservation(
            content="",
            url="https://example.com",
            screenshot_path="/path/to/screenshot.png",
            focused_element_bid="element_123",
            error=False,
            trigger_by_action=ActionType.BROWSE_INTERACTIVE,
            axtree_object={"nodes": []},
            extra_element_properties={},
            filter_visible_only=False,
        )

        with patch(
            "backend.runtime.browser.utils.get_axtree_str", return_value="tree content"
        ):
            result = get_agent_obs_text(obs)

        assert "[Current URL: https://example.com]" in result
        assert "[Focused element bid: element_123]" in result
        assert "[Screenshot saved to: /path/to/screenshot.png]" in result
        assert "[Action executed successfully.]" in result
        assert "tree content" in result

    def test_browse_interactive_with_error(self):
        """Test formats BROWSE_INTERACTIVE observation with error."""
        obs = BrowserOutputObservation(
            content="",
            url="https://example.com",
            error=True,
            last_browser_action_error="Element not found",
            trigger_by_action=ActionType.BROWSE_INTERACTIVE,
            axtree_object={},
            extra_element_properties={},
        )

        with patch("backend.runtime.browser.utils.get_axtree_str", return_value=""):
            result = get_agent_obs_text(obs)

        assert "error message" in result
        assert "Element not found" in result

    def test_browse_url_success(self):
        """Test formats BROWSE observation successfully."""
        obs = BrowserOutputObservation(
            content="Page content here",
            url="https://example.com/page",
            error=False,
            trigger_by_action=ActionType.BROWSE,
        )

        result = get_agent_obs_text(obs)

        assert "[Current URL: https://example.com/page]" in result
        assert "webpage content" in result
        assert "Page content here" in result

    def test_browse_url_with_error(self):
        """Test formats BROWSE observation with error."""
        obs = BrowserOutputObservation(
            content="",
            url="https://bad-url.com",
            error=True,
            last_browser_action_error="DNS resolution failed",
            trigger_by_action=ActionType.BROWSE,
        )

        result = get_agent_obs_text(obs)

        assert "error message" in result
        assert "DNS resolution failed" in result

    def test_invalid_trigger_raises_error(self):
        """Test raises ValueError for invalid trigger_by_action."""
        obs = BrowserOutputObservation(
            content="",
            url="",
            trigger_by_action="INVALID_ACTION",
        )

        with pytest.raises(ValueError, match="Invalid trigger_by_action"):
            get_agent_obs_text(obs)

    def test_browse_interactive_axtree_exception(self):
        """Test handles exception when processing axtree."""
        obs = BrowserOutputObservation(
            content="",
            url="https://example.com",
            error=False,
            trigger_by_action=ActionType.BROWSE_INTERACTIVE,
            axtree_object={"nodes": []},
            extra_element_properties={},
        )

        with patch(
            "backend.runtime.browser.utils.get_axtree_str",
            side_effect=Exception("AXTree parsing error"),
        ):
            result = get_agent_obs_text(obs)

        assert "Error encountered when processing the accessibility tree" in result
        assert "AXTree parsing error" in result


class TestPrepareBrowserAction:
    """Tests for _prepare_browser_action function."""

    def test_browse_url_with_http(self):
        """Test prepares BrowseURLAction with http URL."""
        action = BrowseURLAction(url="https://example.com")

        action_str, asked_url = _prepare_browser_action(action)

        assert action_str == 'goto("https://example.com")'
        assert asked_url == "https://example.com"

    def test_browse_url_without_http(self):
        """Test prepares BrowseURLAction with relative path."""
        action = BrowseURLAction(url="/local/file.html")

        action_str, asked_url = _prepare_browser_action(action)

        assert action_str.startswith('goto("')
        assert "/local/file.html" in asked_url
        assert asked_url != "/local/file.html"  # Should be absolute

    def test_browse_interactive(self):
        """Test prepares BrowseInteractiveAction."""
        action = BrowseInteractiveAction(browser_actions='click("button_123")')

        action_str, asked_url = _prepare_browser_action(action)

        assert action_str == 'click("button_123")'
        assert asked_url == ""


class TestStripDomData:
    """Tests for _strip_dom_data function."""

    def test_clears_dom_fields(self):
        """Test clears DOM-related fields."""
        obs = BrowserOutputObservation(
            content="test",
            url="https://example.com",
            trigger_by_action=ActionType.BROWSE,
            dom_object={"nodes": [1, 2, 3]},
            axtree_object={"tree": "data"},
            extra_element_properties={"prop": "value"},
        )

        _strip_dom_data(obs)

        assert obs.dom_object == {}
        assert obs.axtree_object == {}
        assert obs.extra_element_properties == {}


class TestCreateErrorObservation:
    """Tests for _create_error_observation function."""

    def test_creates_error_for_browse_url(self):
        """Test creates error observation for BrowseURLAction."""
        action = BrowseURLAction(url="https://bad.com")
        error = Exception("Connection timeout")

        obs = _create_error_observation(error, "https://bad.com", action)

        assert obs.error is True
        assert obs.last_browser_action_error == "Connection timeout"
        assert obs.url == "https://bad.com"
        assert obs.trigger_by_action == ActionType.BROWSE

    def test_creates_error_for_browse_interactive(self):
        """Test creates error observation for BrowseInteractiveAction."""
        action = BrowseInteractiveAction(browser_actions='click("btn")')
        error = Exception("Element not clickable")

        obs = _create_error_observation(error, "", action)

        assert obs.error is True
        assert obs.last_browser_action_error == "Element not clickable"
        assert obs.url == ""  # No URL for interactive actions
        assert obs.trigger_by_action == ActionType.BROWSE_INTERACTIVE


class TestCreateBrowserObservation:
    """Tests for _create_browser_observation function."""

    def test_creates_observation_with_all_fields(self):
        """Test creates BrowserOutputObservation with all fields populated."""
        browser_obs = {
            "text_content": "Page text",
            "url": "https://example.com",
            "screenshot": "data:image/png;base64,abc123",
            "set_of_marks": "marks data",
            "image_content": ["img1.png", "img2.png"],
            "open_pages_urls": ["https://page1.com", "https://page2.com"],
            "active_page_index": 1,
            "axtree_object": {"nodes": []},
            "extra_element_properties": {"visible": True},
            "focused_element_bid": "btn_42",
            "last_action": "click",
            "last_action_error": "",
        }
        action = BrowseInteractiveAction(browser_actions="click")

        with patch(
            "backend.runtime.browser.utils.get_agent_obs_text", return_value="formatted"
        ):
            obs = _create_browser_observation(
                browser_obs, "/path/to/screenshot.png", action
            )

        assert obs.url == "https://example.com"
        assert obs.screenshot == "data:image/png;base64,abc123"
        assert obs.screenshot_path == "/path/to/screenshot.png"
        assert obs.goal_image_urls == ["img1.png", "img2.png"]
        assert obs.open_pages_urls == ["https://page1.com", "https://page2.com"]
        assert obs.active_page_index == 1
        assert obs.focused_element_bid == "btn_42"
        assert obs.error is False
        assert obs.content == "formatted"

    def test_creates_observation_with_error(self):
        """Test creates observation with error flag when error exists."""
        browser_obs = {
            "last_action_error": "Element not found",
        }
        action = BrowseURLAction(url="https://example.com")

        with patch(
            "backend.runtime.browser.utils.get_agent_obs_text", return_value="error msg"
        ):
            obs = _create_browser_observation(browser_obs, None, action)

        assert obs.error is True
        assert obs.last_browser_action_error == "Element not found"


@pytest.mark.asyncio
class TestBrowse:
    """Tests for browse async function."""

    async def test_raises_when_browser_is_none(self):
        """Test raises BrowserUnavailableException when browser is None."""
        action = BrowseURLAction(url="https://example.com")

        with pytest.raises(BrowserUnavailableException):
            await browse(action, None)


@pytest.mark.asyncio
class TestSaveScreenshotIfNeeded:
    """Tests for _save_screenshot_if_needed async function."""

    async def test_returns_none_when_no_workspace_dir(self):
        """Test returns None when workspace_dir is None."""
        obs = {"screenshot": "data:image/png;base64,abc123"}
        result = await _save_screenshot_if_needed(obs, None)
        assert result is None

    async def test_returns_none_when_no_screenshot(self):
        """Test returns None when screenshot is missing."""
        obs = {}
        result = await _save_screenshot_if_needed(obs, "/tmp/workspace")
        assert result is None

    async def test_creates_screenshot_directory(self, tmp_path):
        """Test creates .browser_screenshots directory."""
        workspace = str(tmp_path / "workspace")
        Path(workspace).mkdir()

        # Create a simple 1x1 PNG
        Image.new("RGB", (1, 1))
        buffered = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()
        obs = {"screenshot": f"data:image/png;base64,{buffered}"}

        with patch("PIL.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_open.return_value = mock_img
            mock_img.verify = MagicMock()

            await _save_screenshot_if_needed(obs, workspace)

        screenshots_dir = Path(workspace) / ".browser_screenshots"
        assert screenshots_dir.exists()

    async def test_saves_base64_screenshot_directly(self, tmp_path):
        """Test saves base64 screenshot using direct decode."""
        workspace = str(tmp_path / "workspace")
        Path(workspace).mkdir()

        # Create tiny valid PNG
        img = Image.new("RGB", (1, 1), color=(255, 0, 0))
        import io
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        valid_png = base64.b64encode(buffer.getvalue()).decode()

        obs = {"screenshot": f"data:image/png;base64,{valid_png}"}

        result = await _save_screenshot_if_needed(obs, workspace)

        assert result is not None
        assert result.endswith(".png")
        assert Path(result).exists()

    async def test_uses_fallback_on_decode_error(self, tmp_path):
        """Test uses PNG converter fallback when direct decode fails."""
        workspace = str(tmp_path / "workspace")
        Path(workspace).mkdir()

        obs = {"screenshot": "invalid_base64_data"}

        with patch(
            "backend.runtime.browser.utils.png_base64_url_to_image"
        ) as mock_converter:
            mock_img = MagicMock()
            mock_converter.return_value = mock_img

            result = await _save_screenshot_if_needed(obs, workspace)

            mock_converter.assert_called_once()
            mock_img.save.assert_called_once()
            assert result is not None


@pytest.mark.asyncio
class TestBrowseFunction:
    """Tests for browse async function."""

    async def test_raises_when_browser_is_none(self):
        """Test raises BrowserUnavailableException when browser is None."""
        action = BrowseURLAction(url="https://example.com")

        with pytest.raises(BrowserUnavailableException):
            await browse(action, None)

    async def test_executes_browse_url_action(self):
        """Test executes BrowseURLAction successfully."""
        mock_browser = MagicMock()
        mock_browser.step = MagicMock(
            return_value={
                "url": "https://example.com",
                "text_content": "Content",
            }
        )
        action = BrowseURLAction(url="https://example.com")

        with patch(
            "backend.runtime.browser.utils.call_sync_from_async",
            new_callable=AsyncMock,
            return_value={"url": "https://example.com", "text_content": "Content"},
        ), patch(
            "backend.runtime.browser.utils.get_agent_obs_text", return_value="formatted"
        ):
            obs = await browse(action, mock_browser)

        assert isinstance(obs, BrowserOutputObservation)
        assert obs.error is False

    async def test_strips_axtree_when_not_requested(self):
        """Test strips DOM data when return_axtree is False."""
        mock_browser = MagicMock()
        action = BrowseURLAction(url="https://example.com", return_axtree=False)

        with patch(
            "backend.runtime.browser.utils.call_sync_from_async",
            new_callable=AsyncMock,
            return_value={
                "axtree_object": {"nodes": [1, 2, 3]},
                "extra_element_properties": {"key": "val"},
            },
        ), patch(
            "backend.runtime.browser.utils.get_agent_obs_text", return_value="text"
        ):
            obs = await browse(action, mock_browser)

        assert obs.axtree_object == {}
        assert obs.extra_element_properties == {}

    async def test_keeps_axtree_when_requested(self):
        """Test keeps DOM data when return_axtree is True."""
        mock_browser = MagicMock()
        action = BrowseInteractiveAction(
            browser_actions="click", return_axtree=True
        )

        with patch(
            "backend.runtime.browser.utils.call_sync_from_async",
            new_callable=AsyncMock,
            return_value={
                "axtree_object": {"nodes": [1, 2, 3]},
                "extra_element_properties": {"key": "val"},
            },
        ), patch(
            "backend.runtime.browser.utils.get_agent_obs_text", return_value="text"
        ):
            obs = await browse(action, mock_browser)

        assert obs.axtree_object == {"nodes": [1, 2, 3]}
        assert obs.extra_element_properties == {"key": "val"}

    async def test_returns_error_observation_on_exception(self):
        """Test returns error observation when exception occurs."""
        mock_browser = MagicMock()
        action = BrowseURLAction(url="https://bad.com")

        with patch(
            "backend.runtime.browser.utils.call_sync_from_async",
            new_callable=AsyncMock,
            side_effect=Exception("Network error"),
        ):
            obs = await browse(action, mock_browser)

        assert obs.error is True
        assert "Network error" in obs.last_browser_action_error
