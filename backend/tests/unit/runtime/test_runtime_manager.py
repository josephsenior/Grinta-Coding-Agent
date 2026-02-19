"""Unit tests for backend.runtime.runtime_manager — RuntimeManager."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock


from backend.runtime.runtime_manager import (
    RuntimeManager,
    RuntimeServerInfo,
    _ManagedServer,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_info(**overrides) -> RuntimeServerInfo:
    defaults = {
        "process": None,
        "execution_server_port": 9000,
        "app_ports": [],
    }
    defaults.update(overrides)
    return RuntimeServerInfo(**defaults)


# ── RuntimeServerInfo ────────────────────────────────────────────────


class TestRuntimeServerInfo:
    def test_default_fields(self):
        info = RuntimeServerInfo(process=None)
        assert info.execution_server_port is None
        assert info.app_ports == []
        assert info.log_thread is None
        assert info.log_thread_exit_event is None
        assert info.temp_workspace is None

    def test_custom_fields(self):
        proc = MagicMock()
        info = RuntimeServerInfo(
            process=proc,
            execution_server_port=8080,
            app_ports=[3000, 3001],
            temp_workspace="/tmp/test",
        )
        assert info.process is proc
        assert info.execution_server_port == 8080
        assert info.app_ports == [3000, 3001]
        assert info.temp_workspace == "/tmp/test"


# ── _ManagedServer ───────────────────────────────────────────────────


class TestManagedServer:
    def test_touch_updates_last_used(self):
        info = _make_info()
        ms = _ManagedServer(info=info, kind="docker")
        original = ms.last_used_at
        import time

        time.sleep(0.01)
        ms.touch()
        assert ms.last_used_at > original


# ── Warm pool management ────────────────────────────────────────────


class TestWarmPool:
    def test_add_and_acquire(self):
        mgr = RuntimeManager()
        info = _make_info(execution_server_port=9001)
        mgr.add_warm_server("docker", info, metadata={"tag": "v1"})
        assert mgr.warm_count() == 1
        assert mgr.warm_count("docker") == 1
        assert mgr.warm_count("local") == 0

        acquired = mgr.acquire_warm_server("docker")
        assert acquired is info
        assert mgr.warm_count() == 0

    def test_acquire_returns_none_when_empty(self):
        mgr = RuntimeManager()
        assert mgr.acquire_warm_server("docker") is None

    def test_acquire_returns_none_for_wrong_kind(self):
        mgr = RuntimeManager()
        mgr.add_warm_server("docker", _make_info())
        assert mgr.acquire_warm_server("local") is None
        assert mgr.warm_count() == 1

    def test_fifo_ordering(self):
        mgr = RuntimeManager()
        info1 = _make_info(execution_server_port=9001)
        info2 = _make_info(execution_server_port=9002)
        mgr.add_warm_server("docker", info1)
        mgr.add_warm_server("docker", info2)

        acquired = mgr.acquire_warm_server("docker")
        assert acquired is info1

    def test_pop_all_warm(self):
        mgr = RuntimeManager()
        infos = [_make_info(execution_server_port=9000 + i) for i in range(3)]
        for info in infos:
            mgr.add_warm_server("docker", info)
        mgr.add_warm_server("local", _make_info())

        popped = mgr.pop_all_warm("docker")
        assert len(popped) == 3
        assert mgr.warm_count("docker") == 0
        assert mgr.warm_count("local") == 1

    def test_pop_all_warm_empty(self):
        mgr = RuntimeManager()
        assert mgr.pop_all_warm("docker") == []

    def test_warm_count_total(self):
        mgr = RuntimeManager()
        mgr.add_warm_server("docker", _make_info())
        mgr.add_warm_server("local", _make_info())
        mgr.add_warm_server("docker", _make_info())
        assert mgr.warm_count() == 3
        assert mgr.warm_count("docker") == 2
        assert mgr.warm_count("local") == 1


# ── Running session tracking ────────────────────────────────────────


class TestRunningTracking:
    def test_register_and_get(self):
        mgr = RuntimeManager()
        info = _make_info()
        mgr.register_running("s1", "docker", info, metadata={"env": "test"})

        retrieved = mgr.get_running("s1")
        assert retrieved is info
        assert mgr.running_count() == 1

    def test_get_returns_none_for_unknown(self):
        mgr = RuntimeManager()
        assert mgr.get_running("nonexistent") is None

    def test_deregister(self):
        mgr = RuntimeManager()
        info = _make_info()
        mgr.register_running("s1", "docker", info)

        deregistered = mgr.deregister_running("s1")
        assert deregistered is info
        assert mgr.running_count() == 0
        assert mgr.get_running("s1") is None

    def test_deregister_unknown(self):
        mgr = RuntimeManager()
        assert mgr.deregister_running("nope") is None

    def test_running_count_by_kind(self):
        mgr = RuntimeManager()
        mgr.register_running("s1", "docker", _make_info())
        mgr.register_running("s2", "docker", _make_info())
        mgr.register_running("s3", "local", _make_info())
        assert mgr.running_count() == 3
        assert mgr.running_count("docker") == 2
        assert mgr.running_count("local") == 1

    def test_list_session_ids(self):
        mgr = RuntimeManager()
        mgr.register_running("s1", "docker", _make_info())
        mgr.register_running("s2", "local", _make_info())
        mgr.register_running("s3", "docker", _make_info())

        all_ids = mgr.list_session_ids()
        assert set(all_ids) == {"s1", "s2", "s3"}

        docker_ids = mgr.list_session_ids("docker")
        assert set(docker_ids) == {"s1", "s3"}

    def test_heartbeat_updates_timestamp(self):
        mgr = RuntimeManager()
        info = _make_info()
        mgr.register_running("s1", "docker", info)

        import time

        time.sleep(0.01)
        mgr.heartbeat("s1")
        # heartbeat should not raise for unknown session
        mgr.heartbeat("nonexistent")

    def test_heartbeat_unknown_session_no_error(self):
        mgr = RuntimeManager()
        mgr.heartbeat("unknown")  # should not raise


# ── Metrics ──────────────────────────────────────────────────────────


class TestMetrics:
    def test_metrics_snapshot_empty(self):
        mgr = RuntimeManager()
        snap = mgr.metrics_snapshot()
        assert snap == {"warm": {}, "running": {}}

    def test_metrics_snapshot_mixed(self):
        mgr = RuntimeManager()
        mgr.add_warm_server("docker", _make_info())
        mgr.add_warm_server("docker", _make_info())
        mgr.add_warm_server("local", _make_info())
        mgr.register_running("s1", "docker", _make_info())

        snap = mgr.metrics_snapshot()
        assert snap["warm"]["docker"] == 2
        assert snap["warm"]["local"] == 1
        assert snap["running"]["docker"] == 1


# ── iterate_warm_infos ───────────────────────────────────────────────


class TestIterateWarmInfos:
    def test_iterate_all(self):
        mgr = RuntimeManager()
        infos = [_make_info(execution_server_port=9000 + i) for i in range(3)]
        for info in infos:
            mgr.add_warm_server("docker", info)

        iterated = list(mgr.iterate_warm_infos())
        assert len(iterated) == 3

    def test_iterate_filtered(self):
        mgr = RuntimeManager()
        mgr.add_warm_server("docker", _make_info())
        mgr.add_warm_server("local", _make_info())

        docker_infos = list(mgr.iterate_warm_infos("docker"))
        assert len(docker_infos) == 1

    def test_iterate_does_not_mutate(self):
        mgr = RuntimeManager()
        mgr.add_warm_server("docker", _make_info())
        list(mgr.iterate_warm_infos())
        assert mgr.warm_count() == 1


# ── Thread safety (basic smoke) ─────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_add_acquire(self):
        mgr = RuntimeManager()
        errors: list[Exception] = []

        def adder():
            try:
                for _ in range(50):
                    mgr.add_warm_server("docker", _make_info())
            except Exception as e:
                errors.append(e)

        def acquirer():
            try:
                for _ in range(50):
                    mgr.acquire_warm_server("docker")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=adder) for _ in range(3)]
        threads += [threading.Thread(target=acquirer) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
