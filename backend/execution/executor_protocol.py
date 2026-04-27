"""Protocol defining the executor interface for runtime drivers.

This decouples runtime drivers (e.g. ``LocalRuntimeInProcess``) from the
concrete ``RuntimeExecutor`` class. Drivers should depend on
:class:`RuntimeExecutorProtocol` and receive a concrete implementation via
dependency injection or a factory callable.

The protocol mirrors the public surface of
:class:`backend.execution.action_execution_server.RuntimeExecutor` that is
actually exercised by runtime drivers.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.ledger.action import (
    CmdRunAction,
    DebuggerAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    LspQueryAction,
)
from backend.ledger.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)
from backend.ledger.observation import Observation


@runtime_checkable
class RuntimeExecutorProtocol(Protocol):
    """Structural sub-typing interface for runtime executors.

    Any object providing these methods can be used as the executor
    backing a runtime driver — whether it runs in-process, over HTTP,
    or via any other transport.
    """

    # -- lifecycle --------------------------------------------------------

    async def ainit(self) -> None:
        """Perform async initialisation (shell, browser, plugins, …)."""
        ...

    async def hard_kill(self) -> None:
        """Emergency teardown — kill child processes, release resources."""
        ...

    def close(self) -> None:
        """Synchronous cleanup (called during normal shutdown)."""
        ...

    def initialized(self) -> bool:
        """Return *True* once ``ainit`` has completed successfully."""
        ...

    # -- properties -------------------------------------------------------

    @property
    def initial_cwd(self) -> str:
        """The root working directory used by this executor."""
        ...

    # -- action dispatch --------------------------------------------------

    async def run_action(self, action: Any) -> Observation:
        """Generic dispatch — route *action* to the appropriate handler."""
        ...

    async def run(self, action: CmdRunAction) -> Observation: ...

    async def debugger(self, action: DebuggerAction) -> Observation: ...

    async def read(self, action: FileReadAction) -> Observation: ...

    async def write(self, action: FileWriteAction) -> Observation: ...

    async def edit(self, action: FileEditAction) -> Observation: ...

    async def lsp_query(self, action: LspQueryAction) -> Observation: ...

    async def terminal_run(self, action: TerminalRunAction) -> Observation: ...

    async def terminal_input(self, action: TerminalInputAction) -> Observation: ...

    async def terminal_read(self, action: TerminalReadAction) -> Observation: ...

    async def browser_tool(self, action: Any) -> Observation: ...
