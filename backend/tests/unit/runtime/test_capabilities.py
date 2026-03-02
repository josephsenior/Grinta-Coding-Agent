"""Tests for backend.runtime.capabilities — runtime capability detection."""

from unittest.mock import patch

import pytest

from backend.runtime.capabilities import RuntimeCapabilities, detect_capabilities


class TestRuntimeCapabilities:
    """Tests for RuntimeCapabilities dataclass."""

    def test_default_initialization(self):
        """Test creating RuntimeCapabilities with defaults."""
        caps = RuntimeCapabilities()
        assert caps.platform == ""
        assert caps.is_windows is False
        assert caps.has_git is False
        assert caps.has_tmux is False
        assert caps.has_bash is False
        assert caps.can_browse is False
        assert caps.can_mcp is False
        assert caps.can_copy_from_runtime is True
        assert caps.missing_tools == ()

    def test_custom_initialization(self):
        """Test creating RuntimeCapabilities with custom values."""
        caps = RuntimeCapabilities(
            platform="linux",
            is_windows=False,
            has_git=True,
            has_tmux=True,
            has_bash=True,
            can_browse=True,
            can_mcp=True,
            can_copy_from_runtime=True,
            missing_tools=(),
        )
        assert caps.platform == "linux"
        assert caps.has_git is True
        assert caps.has_bash is True
        assert caps.can_browse is True

    def test_frozen_dataclass(self):
        """Test RuntimeCapabilities is frozen (immutable)."""
        caps = RuntimeCapabilities(platform="linux")
        with pytest.raises(AttributeError):
            setattr(caps, "platform", "win32")

    def test_slotted_dataclass(self):
        """Test RuntimeCapabilities uses slots."""
        caps = RuntimeCapabilities()
        # Slotted classes don't have __dict__
        assert not hasattr(caps, "__dict__")


class TestDetectCapabilities:
    """Tests for detect_capabilities function."""

    @patch("sys.platform", "linux")
    @patch("shutil.which")
    def test_linux_with_all_tools(self, mock_which):
        """Test Linux platform with all tools available."""
        mock_which.return_value = "/usr/bin/tool"

        caps = detect_capabilities()

        assert caps.platform == "linux"
        assert caps.is_windows is False
        assert caps.has_git is True
        assert caps.has_tmux is True
        assert caps.has_bash is True
        assert caps.can_mcp is True  # Non-Windows
        assert caps.missing_tools == ()

    @patch("sys.platform", "win32")
    @patch("shutil.which")
    def test_windows_platform(self, mock_which):
        """Test Windows platform detection."""
        mock_which.return_value = "C:\\Program Files\\Git\\bin\\git.exe"

        caps = detect_capabilities()

        assert caps.platform == "win32"
        assert caps.is_windows is True
        assert caps.can_mcp is False  # Disabled on Windows

    @patch("sys.platform", "linux")
    @patch("shutil.which", return_value=None)
    def test_missing_git(self, mock_which):
        """Test detection when git is missing."""
        caps = detect_capabilities()

        assert caps.has_git is False
        assert "git" in caps.missing_tools

    @patch("sys.platform", "linux")
    @patch("shutil.which")
    def test_missing_tmux_and_bash(self, mock_which):
        """Test detection when tmux and bash are missing."""

        def which_side_effect(cmd):
            return "/usr/bin/git" if cmd == "git" else None

        mock_which.side_effect = which_side_effect

        caps = detect_capabilities()

        assert caps.has_git is True
        assert caps.has_tmux is False
        assert caps.has_bash is False
        assert "tmux" in caps.missing_tools
        assert "bash" in caps.missing_tools

    @patch("sys.platform", "win32")
    @patch("shutil.which")
    def test_windows_no_tmux_bash_check(self, mock_which):
        """Test Windows doesn't check for tmux/bash."""
        mock_which.side_effect = lambda cmd: (
            "C:\\Git\\bin\\git.exe" if cmd == "git" else None
        )

        caps = detect_capabilities()

        assert caps.has_git is True
        # tmux/bash not expected on Windows, so not in missing_tools
        assert "tmux" not in caps.missing_tools
        assert "bash" not in caps.missing_tools

    @patch("sys.platform", "darwin")
    @patch("shutil.which")
    def test_macos_platform(self, mock_which):
        """Test macOS platform detection."""
        mock_which.return_value = "/usr/local/bin/tool"

        caps = detect_capabilities()

        assert caps.platform == "darwin"
        assert caps.is_windows is False
        assert caps.can_mcp is True

    @patch("sys.platform", "linux")
    @patch("shutil.which", return_value="/usr/bin/tool")
    def test_browser_enabled(self, mock_which):
        """Test browser capability when enabled."""
        caps = detect_capabilities(enable_browser=True)
        assert caps.can_browse is True

    @patch("sys.platform", "linux")
    @patch("shutil.which", return_value="/usr/bin/tool")
    def test_browser_disabled(self, mock_which):
        """Test browser capability when disabled."""
        caps = detect_capabilities(enable_browser=False)
        assert caps.can_browse is False

    @patch("sys.platform", "linux")
    @patch("shutil.which", return_value="/usr/bin/tool")
    def test_can_copy_from_runtime_always_true(self, mock_which):
        """Test can_copy_from_runtime is always True for local runtime."""
        caps = detect_capabilities()
        assert caps.can_copy_from_runtime is True

    @patch("sys.platform", "linux")
    @patch("shutil.which")
    def test_all_tools_missing(self, mock_which):
        """Test when all tools are missing."""
        mock_which.return_value = None

        caps = detect_capabilities()

        assert caps.has_git is False
        assert caps.has_tmux is False
        assert caps.has_bash is False
        assert len(caps.missing_tools) == 3

    @patch("sys.platform", "linux")
    @patch("shutil.which")
    def test_partial_tools_available(self, mock_which):
        """Test when only some tools are available."""

        def which_side_effect(cmd):
            if cmd == "git":
                return "/usr/bin/git"
            if cmd == "bash":
                return "/bin/bash"
            return None

        mock_which.side_effect = which_side_effect

        caps = detect_capabilities()

        assert caps.has_git is True
        assert caps.has_bash is True
        assert caps.has_tmux is False
        assert caps.missing_tools == ("tmux",)

    @patch("sys.platform", "linux")
    @patch("shutil.which", return_value="/usr/bin/tool")
    def test_detect_is_fast(self, mock_which):
        """Test detect_capabilities is fast (no heavy operations)."""
        import time

        start = time.time()
        caps = detect_capabilities()
        duration = time.time() - start

        # Should complete in under 100ms (very generous)
        assert duration < 0.1
        assert caps is not None

    @patch("sys.platform", "linux")
    @patch("shutil.which", return_value="/usr/bin/tool")
    def test_missing_tools_is_tuple(self, mock_which):
        """Test missing_tools is a tuple (immutable)."""
        caps = detect_capabilities()
        assert isinstance(caps.missing_tools, tuple)

    @patch("sys.platform", "freebsd")
    @patch("shutil.which", return_value="/usr/local/bin/tool")
    def test_other_unix_platform(self, mock_which):
        """Test other Unix-like platform (FreeBSD)."""
        caps = detect_capabilities()

        assert caps.platform == "freebsd"
        assert caps.is_windows is False
        assert caps.can_mcp is True

    @patch("sys.platform", "win32")
    def test_mcp_config_http_on_windows(self):
        """Test that MCP is enabled on Windows if HTTP/SSE servers are configured."""
        class MockServer:
            def __init__(self, t):
                self.type = t
        
        class MockConfig:
            def __init__(self, svrs):
                self.servers = svrs

        # SSE server makes it True
        cfg = MockConfig([MockServer("sse")])
        caps = detect_capabilities(mcp_config=cfg)
        assert caps.can_mcp is True

        # stdio server on Windows remains False
        cfg = MockConfig([MockServer("stdio")])
        caps = detect_capabilities(mcp_config=cfg)
        assert caps.can_mcp is False

    @patch("sys.platform", "win32")
    def test_mcp_config_exception(self):
        """Test that MCP config exceptions are handled gracefully."""
        class BadConfig:
            @property
            def servers(self):
                raise Exception("Boom")

        caps = detect_capabilities(mcp_config=BadConfig())
        # Exception should result in has_http_mcp=False, so on Windows can_mcp=False
        assert caps.can_mcp is False

    @patch("sys.platform", "linux")
    def test_mcp_config_none(self):
        """Test mcp_config=None doesn't crash."""
        caps = detect_capabilities(mcp_config=None)
        assert caps.can_mcp is True  # True on Linux anyway
