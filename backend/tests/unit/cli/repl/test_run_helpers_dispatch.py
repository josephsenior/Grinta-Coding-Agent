import pytest
import asyncio
from unittest.mock import Mock, AsyncMock

from backend.cli.repl.run_helpers_dispatch import (
    _validate_engine_components_ready,
    _read_repl_input,
    _discard_terminal_noise,
)

class DummyHost:
    def __init__(self):
        self._agent = None
        self._llm_registry = None
        self._conversation_stats = None
        self._runtime = None
        self._memory = None
        self._event_stream = None
        self._renderer = Mock()
        self._prompt_ctrl_c_hint_shown = False
        self._consecutive_input_failures = 0
        self._console = Mock()
        self._running = True

    async def _read_non_interactive_input(self):
        return ""

def test_validate_engine_components_ready():
    host = DummyHost()
    assert _validate_engine_components_ready(host) is False
    host._renderer.add_system_message.assert_called_once()
    
    # Now set them all
    host._agent = Mock()
    host._llm_registry = Mock()
    host._conversation_stats = Mock()
    host._runtime = Mock()
    host._memory = Mock()
    host._event_stream = Mock()
    assert _validate_engine_components_ready(host) is True

@pytest.mark.asyncio
async def test_read_repl_input_eof():
    host = DummyHost()
    # No session
    result = await _read_repl_input(host, None)
    assert result is None
    host._console.print.assert_called()

@pytest.mark.asyncio
async def test_read_repl_input_interactive():
    host = DummyHost()
    session = Mock()
    session.prompt_async = AsyncMock(return_value="hello")
    result = await _read_repl_input(host, session)
    assert result == "hello"

@pytest.mark.asyncio
async def test_read_repl_input_keyboard_interrupt():
    host = DummyHost()
    session = Mock()
    session.prompt_async = AsyncMock(side_effect=KeyboardInterrupt)
    result = await _read_repl_input(host, session)
    assert result == ""
    host._console.print.assert_called()


