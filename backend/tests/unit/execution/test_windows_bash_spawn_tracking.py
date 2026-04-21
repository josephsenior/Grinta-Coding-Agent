"""Regression tests for ``Start-Process``-spawned child tracking.

Background: ``Start-Process`` detaches a new process tree from our PowerShell
subprocess, so the PID we register with :class:`TaskCancellationService` is
the shell itself — which exits quickly — not the backgrounded child
(typically a ``python -m http.server`` dev server). On session end we'd leak
that child and the user would end up with an orphaned process holding
a port.

The fix in ``windows_bash.py`` wraps commands that contain ``Start-Process``
with a before/after ``Get-Process`` diff that reports new PIDs back on
stdout inside a sentinel. These tests pin down the *pure* helpers
(wrapper construction and sentinel parsing) so they can run on any OS,
without needing a real PowerShell.
"""

from __future__ import annotations

import sys

import pytest


if sys.platform != 'win32':
    pytest.skip(
        'windows_bash only imports on Windows; helpers are tested via '
        'their module-level definitions which also raise on other OSes.',
        allow_module_level=True,
    )


from backend.execution.utils.windows_bash import (  # noqa: E402
    _SPAWNED_PID_MARKER_RE,
    _START_PROCESS_RE,
    _extract_spawned_pids,
    _wrap_command_for_spawn_tracking,
)


class TestStartProcessDetection:
    """``_START_PROCESS_RE`` must match the intended pattern and nothing else."""

    def test_matches_bare_start_process_invocation(self) -> None:
        assert _START_PROCESS_RE.search(
            'Start-Process python -ArgumentList "-m","http.server","8080"'
        )

    def test_matches_case_insensitively(self) -> None:
        assert _START_PROCESS_RE.search('start-process notepad.exe')
        assert _START_PROCESS_RE.search('START-PROCESS notepad.exe')

    def test_does_not_match_embedded_in_larger_identifier(self) -> None:
        """``MyStart-Process`` or ``Start-ProcessThing`` are *other* cmdlets."""
        assert not _START_PROCESS_RE.search('MyStart-ProcessThing foo')
        assert not _START_PROCESS_RE.search('Start-ProcessingQueue bar')

    def test_matches_after_pipeline(self) -> None:
        assert _START_PROCESS_RE.search(
            'Get-Content args.txt | Start-Process -FilePath pwsh'
        )


class TestCommandWrapper:
    """The wrapper must preserve the user's command verbatim."""

    def test_embeds_user_command_inside_here_string(self) -> None:
        wrapped = _wrap_command_for_spawn_tracking('Start-Process python')
        # Here-string literal is preserved so PowerShell doesn't re-interpret
        # the inner command's quoting / escapes.
        assert "@'\nStart-Process python\n'@" in wrapped

    def test_uses_try_finally_so_errors_still_report_spawns(self) -> None:
        wrapped = _wrap_command_for_spawn_tracking('Start-Process python')
        assert 'try {' in wrapped
        assert '} finally {' in wrapped

    def test_emits_sentinel_only_when_new_pids_exist(self) -> None:
        wrapped = _wrap_command_for_spawn_tracking('Start-Process python')
        assert "if ($__grinta_new.Count -gt 0)" in wrapped
        assert "'___GRINTA_SPAWNED___'" in wrapped
        assert "'___END___'" in wrapped

    def test_handles_commands_with_single_quotes(self) -> None:
        """Single quotes in the user's command must not close the here-string.

        Here-strings (``@'...'@``) only terminate on a line that starts with
        ``'@`` — interior quotes are literal. This test documents that
        contract so a future refactor can't silently break it.
        """
        user_cmd = (
            "Start-Process -FilePath 'python.exe' -ArgumentList "
            "@('-m','http.server','8080')"
        )
        wrapped = _wrap_command_for_spawn_tracking(user_cmd)
        assert user_cmd in wrapped


class TestSpawnedPidExtraction:
    """The sentinel-parse must be robust to edge cases."""

    def test_no_marker_returns_input_unchanged(self) -> None:
        stdout = 'hello world\n'
        cleaned, pids = _extract_spawned_pids(stdout)
        assert cleaned == stdout
        assert pids == []

    def test_extracts_single_pid(self) -> None:
        stdout = 'server started\n___GRINTA_SPAWNED___12345___END___\n'
        cleaned, pids = _extract_spawned_pids(stdout)
        assert pids == [12345]
        assert '___GRINTA_SPAWNED___' not in cleaned
        assert 'server started' in cleaned

    def test_extracts_multiple_pids(self) -> None:
        stdout = (
            'Running\n___GRINTA_SPAWNED___1001,1002,1003___END___\n'
        )
        _cleaned, pids = _extract_spawned_pids(stdout)
        assert pids == [1001, 1002, 1003]

    def test_empty_pid_list_is_no_op(self) -> None:
        """If the PowerShell ``$__grinta_new`` happens to be empty (race
        condition, process already died before the ``finally`` ran) the
        sentinel may show up with nothing between the separators. It must
        parse cleanly rather than blowing up with a ValueError.
        """
        stdout = 'done\n___GRINTA_SPAWNED______END___\n'
        cleaned, pids = _extract_spawned_pids(stdout)
        assert pids == []
        assert '___GRINTA_SPAWNED___' not in cleaned

    def test_ignores_non_numeric_garbage(self) -> None:
        stdout = '___GRINTA_SPAWNED___123,abc,456___END___\n'
        _cleaned, pids = _extract_spawned_pids(stdout)
        assert pids == [123, 456]

    def test_marker_regex_matches_crlf_line_endings(self) -> None:
        """Windows subprocess output uses ``\\r\\n``. The marker regex must
        eat both bytes so the user-visible output doesn't keep a stray
        blank line where the sentinel used to be.
        """
        stdout = '___GRINTA_SPAWNED___99___END___\r\n'
        assert _SPAWNED_PID_MARKER_RE.search(stdout)
        cleaned, pids = _extract_spawned_pids(stdout)
        assert pids == [99]
        assert '___' not in cleaned
