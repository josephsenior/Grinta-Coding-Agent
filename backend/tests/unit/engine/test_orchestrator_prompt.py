"""Tests for backend.engine.tools.prompt — refine_prompt platform logic."""

from __future__ import annotations

import sys
from unittest.mock import patch

from backend.engine.tools.prompt import refine_prompt


class TestRefinePrompt:
    def test_linux_no_change(self):
        with patch.object(sys, "platform", "linux"):
            assert refine_prompt("run bash command") == "run bash command"

    def test_darwin_no_change(self):
        with patch.object(sys, "platform", "darwin"):
            assert refine_prompt("execute_bash foo") == "execute_bash foo"

    def test_windows_replaces_bash(self):
        with patch.object(sys, "platform", "win32"):
            result = refine_prompt("Use bash to run things")
            assert "powershell" in result
            assert "bash" not in result.lower().replace("powershell", "")

    def test_windows_replaces_execute_bash(self):
        with patch.object(sys, "platform", "win32"):
            result = refine_prompt("call execute_bash with args")
            assert "execute_powershell" in result

    def test_windows_does_not_double_replace(self):
        """execute_bash should become execute_powershell, not execute_powershell with an extra replacement."""
        with patch.object(sys, "platform", "win32"):
            result = refine_prompt("execute_bash")
            assert result == "execute_powershell"

    def test_no_bash_unchanged(self):
        with patch.object(sys, "platform", "win32"):
            assert refine_prompt("run shell command") == "run shell command"

    def test_mixed_content(self):
        with patch.object(sys, "platform", "win32"):
            prompt = "Use execute_bash to run bash scripts"
            result = refine_prompt(prompt)
            assert "execute_powershell" in result
            assert "powershell" in result
