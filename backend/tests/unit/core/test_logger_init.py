"""Tests for backend.core.logger initialization logic."""

from __future__ import annotations

import importlib
import logging
import os
from unittest.mock import patch, MagicMock


def test_logger_init_json_and_file(tmp_path):
    """Test logger initialization with JSON logging and file logging enabled."""
    log_dir = os.path.join(tmp_path, "logs")

    with patch.dict(
        os.environ,
        {
            "LOG_JSON": "true",
            "LOG_TO_FILE": "true",
            "LOG_LEVEL": "DEBUG",
            "DEBUG": "true",
            "OTEL_LOG_CORRELATION": "true",
            "LOG_SHIPPING_ENABLED": "true",
        },
    ):
        # Mock dependencies for log shipping
        mock_shipper = MagicMock()
        with patch(
            "backend.core.log_shipping.get_log_shipper", return_value=mock_shipper
        ):
            with patch("backend.core.logger.LOG_DIR", log_dir):
                import backend.core.constants as constants_mod
                import backend.core.logger as logger_mod

                importlib.reload(constants_mod)
                importlib.reload(logger_mod)

                # Check if handlers were added
                assert any(
                    isinstance(h, logging.FileHandler)
                    for h in logger_mod.forge_logger.handlers
                )
                # Check for JSON formatter (should be applied to console handler in JSON mode)
                from pythonjsonlogger.json import JsonFormatter

                assert any(
                    isinstance(h.formatter, JsonFormatter)
                    for h in logger_mod.forge_logger.handlers
                )


def test_logger_init_shipping_failure(tmp_path):
    """Test logger initialization when log shipping fails."""
    with patch.dict(os.environ, {"LOG_SHIPPING_ENABLED": "true"}):
        with patch(
            "backend.core.log_shipping.get_log_shipper",
            side_effect=Exception("shipping fail"),
        ):
            import backend.core.constants as constants_mod
            import backend.core.logger as logger_mod

            importlib.reload(constants_mod)
            importlib.reload(logger_mod)
            # Should not raise, but log warning (covered by reload)


def test_logger_init_no_debug_tty(tmp_path):
    """Test logger initialization without debug/TTY."""
    with patch.dict(os.environ, {"DEBUG": "false", "LOG_LEVEL": "INFO"}):
        with patch("sys.stdout.isatty", return_value=False):
            import backend.core.constants as constants_mod
            import backend.core.logger as logger_mod

            importlib.reload(constants_mod)
            importlib.reload(logger_mod)
            assert not logger_mod.RollingLogger().is_enabled()
