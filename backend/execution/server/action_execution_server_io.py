"""Mixin chain for RuntimeExecutor command, terminal, and file IO.

The original 50 KB monolithic mixin was split into 5 topic-grouped mixins
(PR-11). The full MRO chain is preserved here for backward compat.
"""

from __future__ import annotations

from backend.execution.io_mixins._aes_io_file_mixin import _AesIoFileMixin  # noqa: F401
from backend.execution.io_mixins._aes_io_init_mixin import _AesIoInitMixin  # noqa: F401
from backend.execution.io_mixins._aes_io_run_mixin import _AesIoRunMixin  # noqa: F401
from backend.execution.io_mixins._aes_io_terminal_mixin import (
    _AesIoTerminalMixin,  # noqa: F401
)
from backend.execution.io_mixins._aes_io_workspace_mixin import (
    _AesIoWorkspaceMixin,  # noqa: F401
)


class RuntimeExecutorIOAndTerminalMixin(
    _AesIoInitMixin,
    _AesIoWorkspaceMixin,
    _AesIoRunMixin,
    _AesIoTerminalMixin,
    _AesIoFileMixin,
):
    """Marker class. Inherits all topic-grouped mixins.

    See the individual mixin files for method documentation.
    """
