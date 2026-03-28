"""Tests for backend.gateway.integrations.mcp.error_collector — MCPErrorCollector."""

from __future__ import annotations

import threading
import time


from backend.gateway.integrations.mcp.error_collector import MCPError, MCPErrorCollector


# ---------------------------------------------------------------------------
# MCPError dataclass
# ---------------------------------------------------------------------------


class TestMCPError:
    """Tests for the MCPError dataclass."""

    def test_basic_creation(self):
        err = MCPError(
            timestamp=1000.0,
            server_name="my_server",
            server_type="stdio",
            error_message="Connection refused",
        )
        assert err.timestamp == 1000.0
        assert err.server_name == "my_server"
        assert err.server_type == "stdio"
        assert err.error_message == "Connection refused"
        assert err.exception_details is None

    def test_with_exception_details(self):
        err = MCPError(
            timestamp=1000.0,
            server_name="srv",
            server_type="sse",
            error_message="timeout",
            exception_details="Traceback...",
        )
        assert err.exception_details == "Traceback..."


# ---------------------------------------------------------------------------
# MCPErrorCollector
# ---------------------------------------------------------------------------


class TestMCPErrorCollector:
    """Tests for the MCPErrorCollector class."""

    def test_initially_empty(self):
        c = MCPErrorCollector()
        assert c.has_errors() is False
        assert c.get_error_count() == 0
        assert c.get_errors() == []

    def test_add_error(self):
        c = MCPErrorCollector()
        c.add_error("srv1", "stdio", "failed to connect")
        assert c.has_errors() is True
        assert c.get_error_count() == 1
        errors = c.get_errors()
        assert len(errors) == 1
        assert errors[0].server_name == "srv1"
        assert errors[0].error_message == "failed to connect"

    def test_add_multiple_errors(self):
        c = MCPErrorCollector()
        c.add_error("srv1", "stdio", "err1")
        c.add_error("srv2", "sse", "err2")
        c.add_error("srv3", "stdio", "err3")
        assert c.get_error_count() == 3

    def test_get_errors_returns_copy(self):
        c = MCPErrorCollector()
        c.add_error("srv", "stdio", "err")
        errors = c.get_errors()
        errors.clear()  # mutating the copy
        assert c.get_error_count() == 1  # original unchanged

    def test_clear_errors(self):
        c = MCPErrorCollector()
        c.add_error("srv", "stdio", "err")
        c.clear_errors()
        assert c.has_errors() is False
        assert c.get_error_count() == 0

    def test_disable_collection(self):
        c = MCPErrorCollector()
        c.disable_collection()
        c.add_error("srv", "stdio", "err")
        assert c.has_errors() is False

    def test_enable_after_disable(self):
        c = MCPErrorCollector()
        c.disable_collection()
        c.add_error("srv", "stdio", "err1")
        c.enable_collection()
        c.add_error("srv", "stdio", "err2")
        assert c.get_error_count() == 1  # only the one after re-enable
        assert c.get_errors()[0].error_message == "err2"

    def test_thread_safety(self):
        """Multiple threads adding errors concurrently should not corrupt state."""
        c = MCPErrorCollector()
        errors_per_thread = 100
        num_threads = 5

        def add_errors(thread_id: int):
            for i in range(errors_per_thread):
                c.add_error(f"srv_{thread_id}", "stdio", f"err_{i}")

        threads = [
            threading.Thread(target=add_errors, args=(t,)) for t in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert c.get_error_count() == errors_per_thread * num_threads

    def test_timestamp_is_set(self):
        c = MCPErrorCollector()
        before = time.time()
        c.add_error("srv", "stdio", "err")
        after = time.time()
        err = c.get_errors()[0]
        assert before <= err.timestamp <= after
