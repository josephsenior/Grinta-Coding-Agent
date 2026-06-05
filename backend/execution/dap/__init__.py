"""Debug Adapter Protocol (DAP) client and session management.

Modules:

- :mod:`backend.execution.dap._dap_adapters` — debug-adapter auto-detection
  (looks for ``lldb-vscode``, ``debugpy``, etc. on ``$PATH``).
- :mod:`backend.execution.dap._dap_client` — async DAP client (request/
  response framing, ``reverse-requests``).
- :mod:`backend.execution.dap._dap_errors` — ``DAPError`` and the
  ``DAPStartPhaseError`` exception family.
- :mod:`backend.execution.dap._dap_logging` — DAP-scoped logger helpers.
- :mod:`backend.execution.dap._dap_manager` — ``DAPDebugManager``,
  the public entry point for spawning/joining debug sessions.
- :mod:`backend.execution.dap._dap_session` — ``DAPDebugSession``, a
  single debug-session lifecycle wrapper.

Public API re-exports for backwards compatibility:

>>> from backend.execution.dap import (
...     DAPClient,
...     DAPDebugManager,
...     DAPDebugSession,
...     DAPError,
...     DAPStartPhaseError,
...     detect_debug_adapters,
...     _dap_log,
... )
"""

from __future__ import annotations

from backend.execution.dap._dap_adapters import detect_debug_adapters
from backend.execution.dap._dap_client import DAPClient
from backend.execution.dap._dap_errors import DAPError, DAPStartPhaseError
from backend.execution.dap._dap_logging import _dap_log
from backend.execution.dap._dap_manager import DAPDebugManager
from backend.execution.dap._dap_session import DAPDebugSession

__all__ = [
    'DAPClient',
    'DAPDebugManager',
    'DAPDebugSession',
    'DAPError',
    'DAPStartPhaseError',
    '_dap_log',
    'detect_debug_adapters',
]
