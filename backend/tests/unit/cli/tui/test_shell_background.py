"""Tests for background-detached shell command TUI rendering."""

from __future__ import annotations

from backend.cli.tui.renderer.helpers.shell import cmd_output_is_background_detached
from backend.ledger.observation import CmdOutputMetadata, CmdOutputObservation


def test_cmd_output_is_background_detached_idle_detach_metadata() -> None:
    obs = CmdOutputObservation(
        content='partial output',
        command='npm run dev',
        metadata=CmdOutputMetadata(
            exit_code=-2,
            timeout_kind='idle_detach',
            command_still_running=True,
            partial_output=True,
        ),
    )
    assert cmd_output_is_background_detached(obs) is True


def test_cmd_output_is_background_detached_hard_wall_not_background() -> None:
    obs = CmdOutputObservation(
        content='killed',
        command='sleep 999',
        metadata=CmdOutputMetadata(
            exit_code=124,
            timeout_kind='hard_wall',
            command_still_running=False,
            partial_output=True,
        ),
    )
    assert cmd_output_is_background_detached(obs) is False


def test_cmd_output_is_background_detached_exit_neg2_fallback() -> None:
    obs = CmdOutputObservation(content='', command='pytest -q', exit_code=-2)
    assert cmd_output_is_background_detached(obs) is True
