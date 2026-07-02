"""Protocol defining the executor interface for runtime drivers.

This decouples runtime drivers (e.g. ``LocalRuntimeInProcess``) from the
concrete ``RuntimeExecutor`` class. Drivers should depend on
:class:`RuntimeExecutorProtocol` and receive a concrete implementation via
dependency injection or a factory callable.

The protocol mirrors the public surface of
:class:`backend.execution.server.action_execution_server.RuntimeExecutor` that is
actually exercised by runtime drivers.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.execution.server.debugger import DAPDebugManager
from backend.ledger.action import (
    CmdRunAction,
    DebuggerAction,
    FileEditAction,
    FileReadAction,
    LspQueryAction,
)
from backend.ledger.action.memory_tools import (
    CheckpointAction,
    MemoryPersistAction,
    MemoryRecallAction,
    ScratchpadNoteAction,
    ScratchpadRecallAction,
    WorkingMemoryAction,
)
from backend.ledger.action.search import (
    AnalyzeProjectStructureAction,
    FindSymbolsAction,
    GlobAction,
    GrepAction,
)
from backend.ledger.action.terminal import (
    TerminalCloseAction,
    TerminalInputAction,
    TerminalListAction,
    TerminalReadAction,
    TerminalRunAction,
    TerminalWaitAction,
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

    async def edit(self, action: FileEditAction) -> Observation: ...

    async def lsp_query(self, action: LspQueryAction) -> Observation: ...

    async def grep(self, action: GrepAction) -> Observation: ...

    async def glob(self, action: GlobAction) -> Observation: ...

    async def find_symbols(self, action: FindSymbolsAction) -> Observation: ...

    async def analyze_project_structure(
        self, action: AnalyzeProjectStructureAction
    ) -> Observation: ...

    async def checkpoint(self, action: CheckpointAction) -> Observation: ...

    async def working_memory(self, action: WorkingMemoryAction) -> Observation: ...

    async def memory_persist(self, action: MemoryPersistAction) -> Observation: ...

    async def memory_recall(self, action: MemoryRecallAction) -> Observation: ...

    async def scratchpad_note(self, action: ScratchpadNoteAction) -> Observation: ...

    async def scratchpad_recall(
        self, action: ScratchpadRecallAction
    ) -> Observation: ...

    async def terminal_run(self, action: TerminalRunAction) -> Observation: ...

    async def terminal_input(self, action: TerminalInputAction) -> Observation: ...

    async def terminal_read(self, action: TerminalReadAction) -> Observation: ...

    async def terminal_wait(self, action: TerminalWaitAction) -> Observation: ...

    async def terminal_list(self, action: TerminalListAction) -> Observation: ...

    async def terminal_close(self, action: TerminalCloseAction) -> Observation: ...

    async def browser_tool(self, action: Any) -> Observation: ...

    # -- debugging --------------------------------------------------------

    @property
    def debug_manager(self) -> DAPDebugManager:
        """Access the DAP debug manager for interactive debugger sessions."""
        ...

    # -- browser integration ----------------------------------------------

    def set_browser_structured_extract(self, fn: Any | None) -> None:
        """Register async callback used by ``browser extract``."""
        ...
