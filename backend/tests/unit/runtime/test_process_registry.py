"""Tests for backend.runtime.utils.process_registry — TaskCancellationService."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch


from backend.runtime.utils.process_registry import TaskCancellationService


# ===================================================================
# Init
# ===================================================================

class TestProcessRegistryInit:

    def test_default_label(self):
        svc = TaskCancellationService()
        assert svc._label == "session"

    def test_custom_label(self):
        svc = TaskCancellationService(label="conv-123")
        assert svc._label == "conv-123"

    def test_empty_state(self):
        svc = TaskCancellationService()
        assert len(svc._active_pids) == 0
        assert len(svc._active_processes) == 0
        assert len(svc._kill_callbacks) == 0


# ===================================================================
# register / unregister process / pid
# ===================================================================

class TestRegistration:

    def test_register_process(self):
        svc = TaskCancellationService()
        proc = MagicMock(spec=subprocess.Popen)
        proc.pid = 1234
        svc.register_process(proc)
        assert 1234 in svc._active_pids
        assert 1234 in svc._active_processes

    def test_register_process_no_pid(self):
        svc = TaskCancellationService()
        proc = MagicMock()
        proc.pid = None
        svc.register_process(proc)
        assert len(svc._active_pids) == 0

    def test_register_pid(self):
        svc = TaskCancellationService()
        svc.register_pid(5678)
        assert 5678 in svc._active_pids

    def test_register_pid_zero_ignored(self):
        svc = TaskCancellationService()
        svc.register_pid(0)
        assert 0 not in svc._active_pids

    def test_unregister_process(self):
        svc = TaskCancellationService()
        proc = MagicMock(spec=subprocess.Popen)
        proc.pid = 100
        svc.register_process(proc)
        svc.unregister_process(100)
        assert 100 not in svc._active_pids
        assert 100 not in svc._active_processes

    def test_unregister_pid(self):
        svc = TaskCancellationService()
        svc.register_pid(200)
        svc.unregister_pid(200)
        assert 200 not in svc._active_pids


# ===================================================================
# Kill callbacks
# ===================================================================

class TestKillCallbacks:

    def test_register_callback(self):
        svc = TaskCancellationService()
        cb = MagicMock()
        svc.register_kill_callback("tmux", cb)
        assert "tmux" in svc._kill_callbacks

    def test_register_empty_key_ignored(self):
        svc = TaskCancellationService()
        svc.register_kill_callback("", MagicMock())
        assert len(svc._kill_callbacks) == 0

    def test_unregister_callback(self):
        svc = TaskCancellationService()
        svc.register_kill_callback("key1", MagicMock())
        svc.unregister_kill_callback("key1")
        assert "key1" not in svc._kill_callbacks

    def test_unregister_missing_key(self):
        svc = TaskCancellationService()
        # Should not raise
        svc.unregister_kill_callback("nonexistent")


# ===================================================================
# snapshot
# ===================================================================

class TestSnapshot:

    def test_snapshot_empty(self):
        svc = TaskCancellationService()
        snap = svc.snapshot()
        assert snap["pids"] == 0
        assert snap["process_handles"] == 0

    def test_snapshot_with_entries(self):
        svc = TaskCancellationService()
        proc = MagicMock(spec=subprocess.Popen)
        proc.pid = 42
        svc.register_process(proc)
        svc.register_pid(99)
        snap = svc.snapshot()
        assert snap["pids"] == 2
        assert snap["process_handles"] == 1


# ===================================================================
# cancel_all
# ===================================================================

class TestCancelAll:

    def test_cancels_processes_via_terminate(self):
        svc = TaskCancellationService()
        proc = MagicMock(spec=subprocess.Popen)
        proc.pid = 10
        svc.register_process(proc)
        svc.cancel_all()
        proc.terminate.assert_called_once()
        assert len(svc._active_pids) == 0

    def test_kills_on_timeout(self):
        svc = TaskCancellationService()
        proc = MagicMock(spec=subprocess.Popen)
        proc.pid = 20
        proc.wait.side_effect = subprocess.TimeoutExpired(cmd="cmd", timeout=1.0)
        svc.register_process(proc)
        svc.cancel_all()
        proc.kill.assert_called_once()

    def test_runs_kill_callbacks(self):
        svc = TaskCancellationService()
        cb = MagicMock()
        svc.register_kill_callback("cleanup", cb)
        svc.cancel_all()
        cb.assert_called_once()
        assert len(svc._kill_callbacks) == 0

    def test_callback_exception_does_not_stop(self):
        svc = TaskCancellationService()
        cb1 = MagicMock(side_effect=RuntimeError("fail"))
        cb2 = MagicMock()
        svc.register_kill_callback("cb1", cb1)
        svc.register_kill_callback("cb2", cb2)
        svc.cancel_all()
        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_raw_pid_kill_on_nt(self):
        svc = TaskCancellationService()
        svc.register_pid(999)
        with patch("backend.runtime.utils.process_registry.os.name", "nt"), \
             patch("backend.runtime.utils.process_registry.subprocess.run") as mock_run:
            svc.cancel_all()
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "taskkill" in args
            assert "999" in args

    def test_clears_everything(self):
        svc = TaskCancellationService()
        proc = MagicMock(spec=subprocess.Popen)
        proc.pid = 1
        svc.register_process(proc)
        svc.register_pid(2)
        svc.register_kill_callback("x", MagicMock())
        svc.cancel_all()
        assert len(svc._active_pids) == 0
        assert len(svc._active_processes) == 0
        assert len(svc._kill_callbacks) == 0
