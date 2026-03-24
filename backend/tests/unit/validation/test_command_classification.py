"""Tests for token-oriented command classification used by validation and stuck detection."""

from __future__ import annotations

from backend.events.action.commands import CmdRunAction
from backend.events.observation.commands import CmdOutputObservation
from backend.validation.command_classification import (
    classify_shell_intent,
    find_cmd_output_for_run,
    is_git_diff_command,
    is_test_run_command,
)


def test_is_test_run_command_pytest():
    assert is_test_run_command("pytest -q tests/unit") is True
    assert is_test_run_command("python -m pytest foo") is True


def test_is_test_run_command_npm():
    assert is_test_run_command("npm test") is True
    assert is_test_run_command("pnpm test --filter pkg") is True


def test_is_test_run_command_negative():
    assert is_test_run_command("echo testing things") is False


def test_is_git_diff_command():
    assert is_git_diff_command("git diff HEAD~1") is True
    assert is_git_diff_command("git show abc123") is True
    assert is_git_diff_command("ls") is False


def test_find_cmd_output_pairs_by_cause():
    run = CmdRunAction(command="pytest -q")
    run.id = 42
    obs = CmdOutputObservation(content="ok", command="pytest -q", exit_code=0)
    obs.cause = 42
    hist = [run, obs]
    paired = find_cmd_output_for_run(run, hist, 0)
    assert paired is obs


def test_find_cmd_output_skips_wrong_cause():
    run = CmdRunAction(command="pytest -q")
    run.id = 42
    noise = CmdOutputObservation(content="x", command="other", exit_code=1)
    noise.cause = 99
    obs = CmdOutputObservation(content="ok", command="pytest -q", exit_code=0)
    obs.cause = 42
    hist = [run, noise, obs]
    paired = find_cmd_output_for_run(run, hist, 0)
    assert paired is obs


def test_classify_shell_intent():
    assert classify_shell_intent("pytest -q") == "run_test"
    assert classify_shell_intent("git diff") == "inspect_git"
    assert classify_shell_intent("ls -la") == "inspect_filesystem"
