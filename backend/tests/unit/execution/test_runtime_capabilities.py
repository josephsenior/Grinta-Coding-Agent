"""Tests for backend.execution.capabilities — RuntimeCapabilities & detect_capabilities."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.execution.capabilities import RuntimeCapabilities, detect_capabilities

# ---------------------------------------------------------------------------
# RuntimeCapabilities dataclass tests
# ---------------------------------------------------------------------------


class TestRuntimeCapabilities:
    """Tests for the frozen RuntimeCapabilities dataclass."""

    def test_defaults(self):
        cap = RuntimeCapabilities()
        assert cap.platform == ''
        assert cap.is_windows is False
        assert cap.has_git is False
        assert cap.has_tmux is False
        assert cap.has_bash is False
        assert cap.can_browse is False
        assert cap.can_mcp is True
        assert cap.can_copy_from_runtime is True
        assert cap.missing_tools == ()

    def test_frozen_raises_on_mutation(self):
        cap = RuntimeCapabilities(has_git=True)
        with pytest.raises(AttributeError):
            cap.has_git = False  # type: ignore[misc]

    def test_custom_values_preserved(self):
        cap = RuntimeCapabilities(
            platform='linux',
            is_windows=False,
            has_git=True,
            has_tmux=True,
            has_bash=True,
            can_browse=True,
            can_mcp=True,
            missing_tools=('curl',),
        )
        assert cap.platform == 'linux'
        assert cap.has_git is True
        assert cap.has_tmux is True
        assert cap.can_browse is True
        assert cap.missing_tools == ('curl',)

    def test_equality(self):
        a = RuntimeCapabilities(platform='linux', has_git=True)
        b = RuntimeCapabilities(platform='linux', has_git=True)
        assert a == b

    def test_inequality(self):
        a = RuntimeCapabilities(platform='linux')
        b = RuntimeCapabilities(platform='win32')
        assert a != b


# ---------------------------------------------------------------------------
# detect_capabilities tests
# ---------------------------------------------------------------------------


class TestDetectCapabilities:
    """Tests for the detect_capabilities factory."""

    @patch('backend.execution.capabilities.shutil.which')
    @patch('backend.execution.capabilities.sys')
    def test_linux_all_tools_present(self, mock_sys, mock_which):
        mock_sys.platform = 'linux'
        mock_which.return_value = '/usr/bin/tool'  # all found
        cap = detect_capabilities()
        assert cap.platform == 'linux'
        assert cap.is_windows is False
        assert cap.has_git is True
        assert cap.has_tmux is True
        assert cap.has_bash is True
        assert cap.can_mcp is True
        assert cap.missing_tools == ()

    @patch('backend.execution.capabilities.shutil.which')
    @patch('backend.execution.capabilities.sys')
    def test_windows_platform(self, mock_sys, mock_which):
        mock_sys.platform = 'win32'
        mock_which.return_value = '/usr/bin/tool'
        cap = detect_capabilities()
        assert cap.platform == 'win32'
        assert cap.is_windows is True
        assert cap.can_mcp is True

    @patch('backend.execution.capabilities.shutil.which')
    @patch('backend.execution.capabilities.sys')
    def test_missing_git(self, mock_sys, mock_which):
        mock_sys.platform = 'linux'

        def _which(name):
            return None if name == 'git' else '/usr/bin/tool'

        mock_which.side_effect = _which
        cap = detect_capabilities()
        assert cap.has_git is False
        assert 'git' in cap.missing_tools

    @patch('backend.execution.capabilities.shutil.which')
    @patch('backend.execution.capabilities.sys')
    def test_missing_tmux_on_linux(self, mock_sys, mock_which):
        mock_sys.platform = 'linux'

        def _which(name):
            return None if name == 'tmux' else '/usr/bin/tool'

        mock_which.side_effect = _which
        cap = detect_capabilities()
        assert cap.has_tmux is False
        assert 'tmux' in cap.missing_tools

    @patch('backend.execution.capabilities.shutil.which')
    @patch('backend.execution.capabilities.sys')
    def test_missing_tools_on_windows_excludes_tmux_bash(self, mock_sys, mock_which):
        """On Windows, tmux and bash are not in the 'expected' set."""
        mock_sys.platform = 'win32'
        mock_which.return_value = None  # nothing found
        cap = detect_capabilities()
        # Only git is expected on Windows
        assert 'git' in cap.missing_tools
        assert 'tmux' not in cap.missing_tools
        assert 'bash' not in cap.missing_tools

    @patch('backend.execution.capabilities.shutil.which')
    @patch('backend.execution.capabilities.sys')
    def test_browser_disabled_by_default(self, mock_sys, mock_which):
        mock_sys.platform = 'linux'
        mock_which.return_value = '/usr/bin/tool'
        cap = detect_capabilities(enable_browser=False)
        assert cap.can_browse is False

    @patch('backend.execution.capabilities.shutil.which')
    @patch('backend.execution.capabilities.sys')
    def test_browser_enabled(self, mock_sys, mock_which):
        mock_sys.platform = 'linux'
        mock_which.return_value = '/usr/bin/tool'
        cap = detect_capabilities(enable_browser=True)
        assert cap.can_browse is True

    @patch('backend.execution.capabilities.shutil.which')
    @patch('backend.execution.capabilities.sys')
    def test_can_copy_from_runtime_always_true(self, mock_sys, mock_which):
        mock_sys.platform = 'linux'
        mock_which.return_value = '/usr/bin/tool'
        cap = detect_capabilities()
        assert cap.can_copy_from_runtime is True
