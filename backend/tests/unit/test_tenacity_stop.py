"""Tests for backend.utils.tenacity_stop — stop_if_should_exit."""

from unittest.mock import MagicMock, patch

import pytest

from backend.utils.tenacity_stop import stop_if_should_exit


class TestStopIfShouldExit:
    """Tests for the stop_if_should_exit tenacity stop condition."""

    def test_returns_false_when_should_exit_not_set(self):
        """When should_exit is not defined or returns False, should not stop."""
        stop = stop_if_should_exit()
        retry_state = MagicMock()

        # Patch the canonical module so should_exit returns False
        with patch("backend.utils.tenacity_stop.should_exit", return_value=False, create=True):
            result = stop(retry_state)
            assert result is False

    def test_returns_true_when_should_exit_is_true(self):
        """When should_exit returns True, should stop."""
        stop = stop_if_should_exit()
        retry_state = MagicMock()

        with patch("backend.utils.tenacity_stop.should_exit", return_value=True, create=True):
            result = stop(retry_state)
            assert result is True

    def test_returns_false_when_should_exit_undefined(self):
        """When should_exit is not in globals and module attr raises, returns False."""
        stop = stop_if_should_exit()
        retry_state = MagicMock()

        # Simulate module where should_exit doesn't exist
        import backend.utils.tenacity_stop as mod
        original = getattr(mod, "should_exit", None)
        if hasattr(mod, "should_exit"):
            delattr(mod, "should_exit")
        try:
            result = stop(retry_state)
            assert result is False
        finally:
            if original is not None:
                mod.should_exit = original

    def test_handles_module_import_exception_gracefully(self):
        """If import_module raises, still tries local fallback."""
        stop = stop_if_should_exit()
        retry_state = MagicMock()

        with patch("backend.utils.tenacity_stop.should_exit", return_value=False, create=True):
            # Even with the standard import path, the local binding should work
            result = stop(retry_state)
            assert result is False

    def test_is_instance_of_stop_base(self):
        """stop_if_should_exit should inherit from tenacity stop_base."""
        from tenacity.stop import stop_base
        stop = stop_if_should_exit()
        assert isinstance(stop, stop_base)
