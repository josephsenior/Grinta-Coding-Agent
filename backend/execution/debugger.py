"""Debug Adapter Protocol client and session manager."""

from __future__ import annotations

# Re-exports for backward compatibility. The class definitions, error
# classes, and helper functions have moved to dedicated modules in this
# package; consumers continue to import them from `backend.execution.debugger`.
from backend.core.logger import app_logger as logger  # noqa: E402, F401
from backend.execution._dap_adapters import detect_debug_adapters  # noqa: E402, F401
from backend.execution._dap_client import DAPClient  # noqa: E402, F401
from backend.execution._dap_errors import (  # noqa: E402, F401
    DAPError,
    DAPStartPhaseError,
)
from backend.execution._dap_logging import _dap_log  # noqa: E402, F401
from backend.execution._dap_manager import DAPDebugManager  # noqa: E402, F401
from backend.execution._dap_session import DAPDebugSession  # noqa: E402, F401
