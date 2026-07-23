"""Launch ``backend.cli.entry`` after installing smoke-test patches."""

from __future__ import annotations

import runpy
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_STUB = Path(__file__).with_name('cli_llm_stub_sitecustomize.py')
_spec = spec_from_file_location('grinta_cli_llm_stub', _STUB)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f'Could not load LLM stub from {_STUB}')
_module = module_from_spec(_spec)
_spec.loader.exec_module(_module)


def _patch_agent_loop_end_states() -> None:
    """Treat AWAITING_USER_INPUT as a successful headless completion."""
    import backend.app.agent_control_loop as agent_loop
    from backend.core.enums import AgentState

    original = agent_loop.run_agent_until_done

    async def run_agent_until_done(controller, runtime, memory, end_states):
        extended = list(end_states)
        if AgentState.AWAITING_USER_INPUT not in extended:
            extended.append(AgentState.AWAITING_USER_INPUT)
        await original(controller, runtime, memory, extended)

    agent_loop.run_agent_until_done = run_agent_until_done
    try:
        import backend.app.main as app_main

        app_main.run_agent_until_done = run_agent_until_done
    except Exception:
        pass
    try:
        import backend.cli.tui.screen.lifecycle_dispatch as lifecycle_dispatch

        lifecycle_dispatch.run_agent_until_done = run_agent_until_done
    except Exception:
        pass


def main() -> None:
    _patch_agent_loop_end_states()
    sys.argv = ['backend.cli.entry', *sys.argv[1:]]
    runpy.run_module('backend.cli.entry', run_name='__main__', alter_sys=True)


if __name__ == '__main__':
    main()
