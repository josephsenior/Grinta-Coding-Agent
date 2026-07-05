"""Tests for idle-detach stall hint detection."""

from __future__ import annotations

from backend.execution.utils.shell.stall_hints import (
    append_stall_hint_to_observation,
    detect_shell_stall_reason,
)
from backend.ledger.observation.commands import CmdOutputMetadata, CmdOutputObservation


def test_detect_sudo_password_prompt_in_output() -> None:
    content = 'Reading package lists...\n[sudo] password for dev: '
    hint = detect_shell_stall_reason(content, 'sudo apt-get update')
    assert hint is not None
    assert 'cannot supply' in hint.lower()
    assert 'sudo -n' in hint


def test_detect_dpkg_lock_in_output() -> None:
    content = 'E: Could not get lock /var/lib/dpkg/lock-frontend. It is held by process 1234'
    hint = detect_shell_stall_reason(content, 'sudo rm -f /var/lib/dpkg/lock-frontend')
    assert hint is not None
    assert 'lock' in hint.lower()


def test_detect_sudo_with_no_output_before_detach() -> None:
    hint = detect_shell_stall_reason('', 'sudo rm -f /var/lib/dpkg/lock-frontend')
    assert hint is not None
    assert 'password' in hint.lower()


def test_append_stall_hint_on_idle_detach_observation() -> None:
    metadata = CmdOutputMetadata(
        exit_code=-2,
        timeout_kind='idle_detach',
        command_still_running=True,
    )
    obs = CmdOutputObservation(
        content='[sudo] password for user: ',
        command='sudo apt install llvm',
        metadata=metadata,
    )
    assert append_stall_hint_to_observation(obs) is True
    assert '[INTERACTIVE_STALL]' in obs.content
    assert 'cannot supply' in obs.content.lower()
    assert append_stall_hint_to_observation(obs) is False


def test_no_hint_for_normal_exit() -> None:
    obs = CmdOutputObservation(
        content='done',
        command='echo hi',
        metadata=CmdOutputMetadata(exit_code=0),
    )
    assert append_stall_hint_to_observation(obs) is False
