"""Tests for the OS-agnostic interactive PTY session primitive."""

from __future__ import annotations

import os
import shutil
import time
from unittest.mock import MagicMock

import pytest

from backend.execution.utils.pty_session import (
    CONTROL_SEQUENCES,
    InteractiveSession,
    InteractiveSessionConfig,
    InteractiveSessionError,
    PtyUnavailableError,
    create_interactive_session,
)

IS_WINDOWS = os.name == 'nt'


def _interactive_shell_argv() -> list[str]:
    """Return a long-lived interactive shell appropriate for the OS."""
    if IS_WINDOWS:
        return ['cmd', '/Q', '/K', 'echo READY']
    if shutil.which('bash'):
        return ['bash', '--norc', '--noprofile', '-i']
    return ['sh', '-i']


def _one_shot_argv(payload: str = 'hello-pty') -> list[str]:
    """Return an argv that prints ``payload`` then exits."""
    if IS_WINDOWS:
        return ['cmd', '/c', f'echo {payload}']
    return ['sh', '-c', f'echo {payload}']


def _wait_for(condition, *, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Pure-logic tests (no real PTY spawn) — work on every platform
# ---------------------------------------------------------------------------


class TestConfigNormalization:
    def test_list_argv_is_preserved(self) -> None:
        cfg = InteractiveSessionConfig(argv=['bash', '-c', 'echo hi'])
        assert cfg.normalized_argv() == ['bash', '-c', 'echo hi']

    def test_string_argv_is_tokenized_on_posix(self) -> None:
        cfg = InteractiveSessionConfig(argv='bash -c "echo hi"')
        if IS_WINDOWS:
            assert cfg.normalized_argv() == ['bash -c "echo hi"']
        else:
            assert cfg.normalized_argv() == ['bash', '-c', 'echo hi']

    def test_empty_argv_raises(self) -> None:
        cfg = InteractiveSessionConfig(argv=[])
        with pytest.raises(InteractiveSessionError):
            cfg.normalized_argv()


class TestControlSequences:
    @pytest.mark.parametrize(
        ('alias', 'expected'),
        [('c', '\x03'), ('ctrl-c', '\x03'), ('d', '\x04'), ('eof', '\x04')],
    )
    def test_known_aliases(self, alias: str, expected: str) -> None:
        assert CONTROL_SEQUENCES[alias] == expected


class TestBufferSemantics:
    """Exercise the buffer logic without touching a real PTY."""

    def _make_session(self, buffer_chars: int = 32) -> InteractiveSession:
        cfg = InteractiveSessionConfig(argv=['noop'], buffer_chars=buffer_chars)
        return InteractiveSession(cfg)

    def test_append_and_peek(self) -> None:
        session = self._make_session()
        session._append_to_buffer('hello')
        assert session.peek() == 'hello'
        assert session.produced_chars == 5
        assert session.dropped_chars == 0

    def test_consume_clears_buffer(self) -> None:
        session = self._make_session()
        session._append_to_buffer('abc')
        assert session.read(consume=True) == 'abc'
        assert session.peek() == ''
        assert session.produced_chars == 3

    def test_nonconsume_preserves_buffer(self) -> None:
        session = self._make_session()
        session._append_to_buffer('abc')
        assert session.read(consume=False) == 'abc'
        assert session.peek() == 'abc'

    def test_buffer_trims_when_oversized(self) -> None:
        session = self._make_session(buffer_chars=8)
        session._append_to_buffer('1234567890ABCDEF')
        assert len(session.peek()) == 8
        assert session.peek() == '9' * 0 + '9' + '0ABCDEF'
        assert session.produced_chars == 16
        assert session.dropped_chars == 8

    def test_read_since_returns_incremental_slice(self) -> None:
        session = self._make_session()
        session._append_to_buffer('foo')
        chunk1, offset1 = session.read_since(0)
        assert chunk1 == 'foo'
        assert offset1 == 3

        session._append_to_buffer('bar')
        chunk2, offset2 = session.read_since(offset1)
        assert chunk2 == 'bar'
        assert offset2 == 6

        chunk3, offset3 = session.read_since(offset2)
        assert chunk3 == ''
        assert offset3 == 6

    def test_read_since_handles_dropped_window(self) -> None:
        session = self._make_session(buffer_chars=4)
        session._append_to_buffer('12345678')  # 4 chars dropped
        chunk, offset = session.read_since(0)
        assert chunk == '5678'
        assert offset == 8


class TestLifecycleGuards:
    def test_double_start_raises(self) -> None:
        session = InteractiveSession(InteractiveSessionConfig(argv=_one_shot_argv('x')))
        session._started = True  # simulate prior start without real spawn
        with pytest.raises(InteractiveSessionError):
            session.start()

    def test_write_before_start_raises(self) -> None:
        session = InteractiveSession(InteractiveSessionConfig(argv=_one_shot_argv('x')))
        with pytest.raises(InteractiveSessionError):
            session.write('hi')

    def test_write_after_close_raises(self) -> None:
        session = InteractiveSession(InteractiveSessionConfig(argv=_one_shot_argv('x')))
        session._started = True
        session._closed = True
        with pytest.raises(InteractiveSessionError):
            session.write('hi')

    def test_resize_requires_positive_dimensions(self) -> None:
        session = InteractiveSession(InteractiveSessionConfig(argv=_one_shot_argv('x')))
        session._started = True
        session._backend = MagicMock()
        with pytest.raises(InteractiveSessionError):
            session.resize(0, 80)
        with pytest.raises(InteractiveSessionError):
            session.resize(24, -1)


class TestPtyUnavailableHandling:
    """Simulate missing backend libraries to verify the error path."""

    def test_backend_missing_raises_pty_unavailable(self, monkeypatch) -> None:
        import backend.execution.utils.pty_session as mod

        def _raise(*_args, **_kwargs):
            raise PtyUnavailableError('forced for test')

        monkeypatch.setattr(mod, '_spawn_backend', _raise)
        session = InteractiveSession(InteractiveSessionConfig(argv=_one_shot_argv('x')))
        with pytest.raises(PtyUnavailableError):
            session.start()


# ---------------------------------------------------------------------------
# Live PTY tests — require the platform backend to be importable
# ---------------------------------------------------------------------------


def _platform_backend_available() -> bool:
    try:
        if IS_WINDOWS:
            import winpty  # noqa: F401
        else:
            import ptyprocess  # noqa: F401
    except ImportError:
        return False
    return True


requires_live_pty = pytest.mark.skipif(
    not _platform_backend_available(),
    reason='platform PTY backend not installed',
)


@requires_live_pty
class TestLivePtySession:
    def test_one_shot_command_produces_expected_output(self) -> None:
        session = create_interactive_session(_one_shot_argv('pty-works'))
        try:
            assert _wait_for(lambda: 'pty-works' in session.peek(), timeout=5.0)
            assert _wait_for(lambda: not session.is_alive(), timeout=5.0)
        finally:
            session.close()

    def test_exit_code_is_captured(self) -> None:
        session = create_interactive_session(_one_shot_argv('done'))
        try:
            session.wait(timeout=5.0)
        finally:
            code = session.close()
        assert code == 0

    def test_pid_is_exposed_after_start(self) -> None:
        session = create_interactive_session(_one_shot_argv('pid-check'))
        try:
            assert isinstance(session.pid, int)
            assert session.pid > 0
        finally:
            session.close()

    def test_context_manager_terminates_child(self) -> None:
        argv = _interactive_shell_argv()
        with create_interactive_session(argv, start=False) as session:
            assert session.is_started
            assert session.is_alive() or session.exit_code is not None
        assert session.is_closed

    def test_resize_does_not_error(self) -> None:
        argv = _interactive_shell_argv()
        session = create_interactive_session(argv)
        try:
            session.resize(rows=30, cols=100)
        finally:
            session.close()

    def test_interactive_write_reads_back_output(self) -> None:
        argv = _interactive_shell_argv()
        session = create_interactive_session(argv)
        try:
            marker = 'grinta-roundtrip-OK'
            session.send_line(f'echo {marker}')
            assert _wait_for(
                lambda: marker in session.peek(),
                timeout=5.0,
            ), f'marker not seen; buffer={session.peek()!r}'
        finally:
            session.close()

    def test_read_since_walks_forward(self) -> None:
        argv = _interactive_shell_argv()
        session = create_interactive_session(argv)
        try:
            session.send_line('echo first-chunk')
            assert _wait_for(lambda: 'first-chunk' in session.peek(), timeout=5.0)
            _, offset = session.read_since(0)

            session.send_line('echo second-chunk')
            assert _wait_for(lambda: 'second-chunk' in session.peek(), timeout=5.0)
            tail, next_offset = session.read_since(offset)
            assert 'second-chunk' in tail
            assert next_offset >= offset
        finally:
            session.close()

    def test_close_sets_exit_code_and_marks_closed(self) -> None:
        session = create_interactive_session(_one_shot_argv('close-check'))
        time.sleep(0.2)
        session.close()
        assert session.is_closed
        assert not session.is_alive()
