"""Tests for backend.runtime.utils.tool_registry — ToolInfo and ToolRegistry."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from backend.runtime.utils.tool_registry import ToolInfo, ToolRegistry


# ── ToolInfo dataclass ────────────────────────────────────────────────

class TestToolInfo:
    def test_defaults(self):
        info = ToolInfo(name="git", available=True)
        assert info.name == "git"
        assert info.available is True
        assert info.path is None
        assert info.version is None
        assert info.fallback is None

    def test_all_fields(self):
        info = ToolInfo(
            name="rg", available=True, path="/usr/bin/rg",
            version="14.0.0", fallback="grep",
        )
        assert info.path == "/usr/bin/rg"
        assert info.version == "14.0.0"
        assert info.fallback == "grep"


# ── _check_command ────────────────────────────────────────────────────

class TestCheckCommand:
    def test_returns_true_on_success(self):
        reg = object.__new__(ToolRegistry)
        reg._tools = {}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            assert reg._check_command("git", ["--version"]) is True

    def test_returns_false_on_not_found(self):
        reg = object.__new__(ToolRegistry)
        reg._tools = {}
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert reg._check_command("nope", []) is False

    def test_returns_false_on_timeout(self):
        reg = object.__new__(ToolRegistry)
        reg._tools = {}
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)):
            assert reg._check_command("slow", []) is False

    def test_returns_false_on_nonzero(self):
        reg = object.__new__(ToolRegistry)
        reg._tools = {}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="")
            assert reg._check_command("fail", []) is False

    def test_check_stderr_returns_true(self):
        reg = object.__new__(ToolRegistry)
        reg._tools = {}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="Usage: findstr")
            assert reg._check_command("findstr", ["/?"], check_stderr=True) is True


# ── _get_version_output ───────────────────────────────────────────────

class TestGetVersionOutput:
    def test_returns_first_line(self):
        reg = object.__new__(ToolRegistry)
        reg._tools = {}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="git version 2.43.0\nmore info\n"
            )
            assert reg._get_version_output("git", ["--version"]) == "git version 2.43.0"

    def test_returns_none_on_error(self):
        reg = object.__new__(ToolRegistry)
        reg._tools = {}
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert reg._get_version_output("nope", []) is None


# ── Public properties ─────────────────────────────────────────────────

class TestRegistryProperties:
    def _build_registry(self, tools: dict[str, ToolInfo]) -> ToolRegistry:
        reg = object.__new__(ToolRegistry)
        reg._tools = tools
        return reg

    def test_shell_type(self):
        reg = self._build_registry({"shell": ToolInfo("pwsh", True)})
        assert reg.shell_type == "pwsh"

    def test_has_bash_true(self):
        reg = self._build_registry({"shell": ToolInfo("bash", True)})
        assert reg.has_bash is True

    def test_has_bash_false(self):
        reg = self._build_registry({"shell": ToolInfo("pwsh", True)})
        assert reg.has_bash is False

    def test_has_powershell(self):
        reg = self._build_registry({"shell": ToolInfo("pwsh", True)})
        assert reg.has_powershell is True

    def test_has_powershell_legacy(self):
        reg = self._build_registry({"shell": ToolInfo("powershell", True)})
        assert reg.has_powershell is True

    def test_has_tmux(self):
        reg = self._build_registry({"tmux": ToolInfo("tmux", True)})
        assert reg.has_tmux is True

    def test_has_tmux_false(self):
        reg = self._build_registry({"tmux": ToolInfo("tmux", False)})
        assert reg.has_tmux is False

    def test_has_git(self):
        reg = self._build_registry({"git": ToolInfo("git", True)})
        assert reg.has_git is True

    def test_search_tool(self):
        reg = self._build_registry({"search": ToolInfo("ripgrep", True)})
        assert reg.search_tool == "ripgrep"

    def test_has_ripgrep(self):
        reg = self._build_registry({"search": ToolInfo("ripgrep", True)})
        assert reg.has_ripgrep is True

    def test_has_ripgrep_false(self):
        reg = self._build_registry({"search": ToolInfo("grep", True)})
        assert reg.has_ripgrep is False

    def test_get_tool_info(self):
        info = ToolInfo("git", True, version="2.43")
        reg = self._build_registry({"git": info})
        assert reg.get_tool_info("git") is info

    def test_get_tool_info_missing(self):
        reg = self._build_registry({})
        assert reg.get_tool_info("missing") is None

    def test_require_git_passes(self):
        reg = self._build_registry({"git": ToolInfo("git", True)})
        reg.require_git()  # Should not raise

    def test_require_git_raises(self):
        reg = self._build_registry({"git": ToolInfo("git", False)})
        with pytest.raises(RuntimeError, match="Git is required"):
            reg.require_git()

    def test_defaults_when_no_tools(self):
        reg = self._build_registry({})
        assert reg.has_git is False
        assert reg.has_tmux is False
        assert reg.has_bash is False
