"""Chunk _fn_call_examples of fn_call_converter.

Extracted from backend/inference/fn_call_converter.py to keep the
parent module under the per-file LOC budget.

Convert function calling messages to non-function calling messages and vice versa.

This will inject prompts so that models that doesn't support function calling
can still be used with function calling agents.

**Pseudo-XML tool call contract (non-native / string mode)**

Models emit a single call per assistant message, shaped like::

    <function=name>
    <parameter=key>value</parameter>
    ...
    </function>

- Whitespace is allowed around ``=``, tags, and names by strict tag parsing.
- Tag names are case-sensitive as written; patterns allow flexible spacing.
- Parameter bodies use non-greedy matching up to the first literal
  ``</parameter>``; avoid embedding that substring inside values.
- ``STOP_WORDS`` (e.g. ``"</function"``) is used for streaming boundaries only.
    ``_fix_stopword`` no longer mutates outputs.

**Tool result lines**

User-side history uses strict structured payload blocks::

    <app_tool_result_json>{"tool_name":"...","content":...}</app_tool_result_json>

This avoids ambiguous free-text parsing and guarantees deterministic round-trip.

**Native tool calls**

When the stack uses provider-native tool calls, this markup is bypassed; these
patterns apply only to the string conversion paths. Prefer models and providers
that expose native function/tool calling so traffic stays on structured tool
messages instead of this pseudo-XML path.

Tool result line syntax is shared via :mod:`backend.inference.tool_result_format`.
"""

from __future__ import annotations

import hashlib
import logging
from threading import Lock

from backend.core.tools.tool_names import (
    CREATE_FILE_TOOL_NAME,
)

logger = logging.getLogger(__name__)

# coverage: ignore file

SYSTEM_PROMPT_SUFFIX_TEMPLATE = '\nYou have access to the following functions:\n\n{description}\n\nIf you choose to call a function ONLY reply in the following format with NO suffix:\n\n<function=example_function_name>\n<parameter=example_parameter_1>value_1</parameter>\n<parameter=example_parameter_2>\nThis is the value for the second parameter\nthat can span\nmultiple lines\n</parameter>\n</function>\n\n<IMPORTANT>\nReminder:\n- Function calls MUST follow the specified format, start with <function= and end with </function>\n- Required parameters MUST be specified\n- In this fallback parser mode, call one function at a time\n- You may provide optional reasoning for your function call in natural language BEFORE the function call, but NOT after.\n- If there is no function call available, answer the question like normal with your current knowledge and do not tell the user about function calls\n</IMPORTANT>\n'
STOP_WORDS = ['</function']

_STRICT_PARSE_SUCCESS = 'strict_parse_success'
_STRICT_PARSE_FAILURE = 'strict_parse_failure'
_MALFORMED_PAYLOAD_REJECTION = 'malformed_payload_rejection'
_XML_TRAILING_TEXT = 'xml_trailing_text'
_FN_CALL_PARSE_COUNTER_KEYS = (
    _STRICT_PARSE_SUCCESS,
    _STRICT_PARSE_FAILURE,
    _MALFORMED_PAYLOAD_REJECTION,
    _XML_TRAILING_TEXT,
)
_fn_call_parse_counters_lock = Lock()
_fn_call_parse_counters: dict[str, int] = {
    key: 0 for key in _FN_CALL_PARSE_COUNTER_KEYS
}

_RETRY_GUARD_LOCK = Lock()
_RETRY_GUARD: dict[str, str] = {}
_RETRY_GUARD_MAX_ENTRIES = 1000

TERMINAL_EXAMPLE_KEY = 'terminal_command'


def _increment_parse_counter(counter_name: str) -> None:
    """Increment one parse telemetry counter in a threadsafe way."""
    with _fn_call_parse_counters_lock:
        _fn_call_parse_counters[counter_name] += 1


def get_fn_call_parse_telemetry_counters() -> dict[str, int]:
    """Return a snapshot of strict parser telemetry counters."""
    with _fn_call_parse_counters_lock:
        return dict(_fn_call_parse_counters)


def reset_fn_call_parse_telemetry_counters() -> None:
    """Reset strict parser telemetry counters.

    Primarily used by unit tests to keep assertions isolated.
    """
    with _fn_call_parse_counters_lock:
        for key in _FN_CALL_PARSE_COUNTER_KEYS:
            _fn_call_parse_counters[key] = 0


def _compute_content_hash(content: str) -> str:
    """Compute a short hash of content for retry tracking."""
    return hashlib.sha256(content[:4096].encode()).hexdigest()[:16]


def _check_retry_guard(
    tool_name: str, raw_hash: str, error_code: str
) -> tuple[bool, str]:
    """Check if a (tool, hash, error) combination should be allowed to retry.

    Returns (should_continue, reason). If should_continue is False, reason
    explains why the retry was blocked.
    """
    key = f'{tool_name}:{error_code}'
    with _RETRY_GUARD_LOCK:
        if len(_RETRY_GUARD) > _RETRY_GUARD_MAX_ENTRIES:
            _RETRY_GUARD.clear()
        if key in _RETRY_GUARD and _RETRY_GUARD[key] == raw_hash:
            return False, (
                f'Retry guard triggered: {tool_name} with same '
                f'hash {raw_hash} and error {error_code}. '
                'Stop auto-retry and report as system/tool error.'
            )
        _RETRY_GUARD[key] = raw_hash
    return True, ''


def _log_xml_parser_diagnostics(
    fn_name: str,
    fn_body: str,
    param_body: str | None,
    error_code: str | None,
    trailing_text: str | None,
    last_end: int,
    param_count: int,
) -> None:
    """Log structured diagnostics for XML tool call parsing.

    This helps diagnose parser issues without changing behavior.
    """
    body_used = param_body if param_body is not None else fn_body
    diagnostics = {
        'tool': fn_name,
        'parser_mode': 'xml',
        'body_len': len(body_used),
        'body_hash': _compute_content_hash(body_used),
        'trailing_text_preview': (trailing_text[:200] if trailing_text else None),
        'trailing_len': len(trailing_text) if trailing_text else 0,
        'last_end': last_end,
        'param_count': param_count,
        'error_code': error_code,
    }
    logger.debug('XML parser diagnostics: %s', diagnostics)


TOOL_EXAMPLES = {
    TERMINAL_EXAMPLE_KEY: {
        'check_dir': '\nASSISTANT: Sure! Let me first check the current directory:\n<function=execute_bash>\n<parameter=action>run</parameter>\n<parameter=command>pwd && ls</parameter>\n<parameter=security_risk>LOW</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\n/workspace\nApp@runtime:~/workspace$\n',
        'run_server': "\nASSISTANT:\nLet me run the Python file for you:\n<function=execute_bash>\n<parameter=action>run</parameter>\n<parameter=command>python3 app.py > server.log 2>&1 &</parameter>\n<parameter=security_risk>MEDIUM</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\n[1] 121\n[1]+  Exit 1                  python3 app.py > server.log 2>&1\n\nASSISTANT:\nLooks like the server was running with PID 121 then crashed. Let me check the server log:\n<function=execute_bash>\n<parameter=action>run</parameter>\n<parameter=command>cat server.log</parameter>\n<parameter=security_risk>LOW</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\nTraceback (most recent call last):\n  File \"/workspace/app.py\", line 2, in <module>\n    from flask import Flask\nModuleNotFoundError: No module named 'flask'\n\nASSISTANT:\nLooks like the server crashed because the `flask` module is not installed. Let me install the `flask` module for you:\n<function=execute_bash>\n<parameter=action>run</parameter>\n<parameter=command>pip3 install flask</parameter>\n<parameter=security_risk>MEDIUM</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\nDefaulting to user installation because normal site-packages is not writeable\nCollecting flask\n  Using cached flask-3.0.3-py3-none-any.whl (101 kB)\nCollecting blinker>=1.6.2\n  Using cached blinker-1.7.0-py3-none-any.whl (13 kB)\nCollecting Werkzeug>=3.0.0\n  Using cached werkzeug-3.0.2-py3-none-any.whl (226 kB)\nCollecting click>=8.1.3\n  Using cached click-8.1.7-py3-none-any.whl (97 kB)\nCollecting itsdangerous>=2.1.2\n  Using cached itsdangerous-2.2.0-py3-none-any.whl (16 kB)\nRequirement already satisfied: Jinja2>=3.1.2 in /home/App/.local/lib/python3.10/site-packages (from flask) (3.1.3)\nRequirement already satisfied: MarkupSafe>=2.0 in /home/App/.local/lib/python3.10/site-packages (from Jinja2>=3.1.2->flask) (2.1.5)\nInstalling collected packages: Werkzeug, itsdangerous, click, blinker, flask\nSuccessfully installed Werkzeug-3.0.2 blinker-1.7.0 click-8.1.7 flask-3.0.3 itsdangerous-2.2.0\n\nASSISTANT:\nThe `flask` module is installed successfully. Let me run the Python file again:\n<function=execute_bash>\n<parameter=action>run</parameter>\n<parameter=command>python3 app.py > server.log 2>&1 &</parameter>\n<parameter=security_risk>MEDIUM</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\n[1] 124\n\nASSISTANT:\nLet me check the server log again:\n<function=execute_bash>\n<parameter=action>run</parameter>\n<parameter=command>cat server.log</parameter>\n<parameter=security_risk>LOW</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\n* Serving Flask app 'app'\n * Debug mode: off\nWARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.\n * Running on http://127.0.0.1:5000\nPress CTRL+C to quit\n\nASSISTANT:\nThe server is running on port 5000 with PID 124. You can access the list of numbers by visiting http://127.0.0.1:5000. If you have any further questions, feel free to ask!\n",
        'kill_server': '\nUSER: Now kill the server, make it display the numbers in a table format.\n\nASSISTANT:\nSure! Let me stop the server first:\n<function=execute_bash>\n<parameter=action>run</parameter>\n<parameter=command>kill 124</parameter>\n<parameter=security_risk>MEDIUM</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\n[1]+  Terminated              python3 app.py > server.log 2>&1\n',
        'run_server_again': '\nASSISTANT:\nRunning the updated file:\n<function=execute_bash>\n<parameter=action>run</parameter>\n<parameter=command>python3 app.py > server.log 2>&1 &</parameter>\n<parameter=security_risk>MEDIUM</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\n[1] 126\n\nASSISTANT:\nThe server is running on port 5000 with PID 126. You can access the list of numbers in a table format by visiting http://127.0.0.1:5000.\n',
    },
    'create': {
        'file': "\nASSISTANT:\nThere is no app.py in the current directory. Let me create it:\n<function=create_file>\n<parameter=path>app.py</parameter>\n<parameter=security_risk>LOW</parameter>\n<parameter=content>\nfrom flask import Flask\napp = Flask(__name__)\n\n@app.route('/')\ndef index():\n    numbers = list(range(1, 11))\n    return str(numbers)\n\nif __name__ == '__main__':\n    app.run(port=5000)\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [create_file]:\nFile created successfully at: app.py",
    },
    'browser': {
        'view_page': "\nASSISTANT:\nLet me check how the page looks in the browser:\n<function=browser>\n<parameter=code>\ngoto('http://127.0.0.1:5000')\nnoop(1000)  # Wait for page to load\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [browser]:\n[Browser shows the numbers in a table format]\n",
    },
}


def get_example_for_tools(tools: list[dict], mode: str = 'agent') -> str:
    """Generate an in-context learning example based on available tools.

    Args:
        tools: Available tool definitions.
        mode: Interaction mode ('agent' or 'plan').

    Returns:
        str: The built example string, or empty string if no tools found.

    """
    from backend.utils.terminal.terminal_contract import get_terminal_tool_name

    # Extract available tools from the tools list
    available_tools = _extract_available_tools(tools)

    if not available_tools:
        return ''

    # Build the example step by step
    example = _build_example_header()
    example += _build_example_steps(available_tools, mode=mode)
    example += _build_example_footer()

    example_str = example.lstrip()
    terminal_tool = get_terminal_tool_name()
    if terminal_tool != 'execute_bash':
        example_str = example_str.replace('execute_bash', terminal_tool)
    example_str = _adapt_example_commands_to_terminal(example_str, terminal_tool)

    return example_str


def _adapt_example_commands_to_terminal(
    example_str: str,
    terminal_tool: str,
) -> str:
    """Rewrite shell snippets in examples to match the active terminal contract."""
    from backend.utils.terminal.terminal_contract import uses_powershell_terminal
    if uses_powershell_terminal():
        substitutions = (
            ('pwd && ls', 'Get-Location; Get-ChildItem'),
            (
                'python3 app.py > server.log 2>&1 &',
                "Start-Process -FilePath python -ArgumentList 'app.py' "
                "-RedirectStandardOutput 'server.log' "
                "-RedirectStandardError 'server.log' -PassThru",
            ),
            ('cat server.log', 'Get-Content server.log'),
            ('pip3 install flask', 'pip install flask'),
            ('kill 124', 'Stop-Process -Id 124'),
            ('python3 app.py', 'python app.py'),
        )
        for old, new in substitutions:
            example_str = example_str.replace(old, new)
    return example_str


def _extract_available_tools(tools: list[dict]) -> set[str]:
    """Extract available tool names from the tools list."""
    available_tools = set()

    for tool in tools:
        if tool['type'] == 'function':
            name = tool['function']['name']
            tool_mapping = _get_tool_name_mapping()
            if name in tool_mapping:
                available_tools.add(tool_mapping[name])

    return available_tools


def _get_tool_name_mapping() -> dict[str, str]:
    """Get mapping from tool names to example keys."""
    from backend.utils.terminal.terminal_contract import get_terminal_tool_name

    return {
        get_terminal_tool_name(): TERMINAL_EXAMPLE_KEY,
        'execute_bash': TERMINAL_EXAMPLE_KEY,
        'execute_powershell': TERMINAL_EXAMPLE_KEY,
        CREATE_FILE_TOOL_NAME: 'create',
    }


def _build_example_header() -> str:
    """Build the header section of the example."""
    return (
        "Here's a running example of how to perform a task with the provided tools.\n\n"
        '--------------------- START OF EXAMPLE ---------------------\n\n'
        'USER: Create a list of numbers from 1 to 10, and display them in a web page at port 5000.\n\n'
    )


def _build_example_steps(available_tools: set[str], mode: str = 'agent') -> str:
    """Build the example steps based on available tools.

    Args:
        available_tools: Set of available tool names.
        mode: Interaction mode ('agent' or 'plan').

    Returns:
        str: The built example steps string.

    """
    example_builder = ExampleStepBuilder(available_tools, mode=mode)
    return example_builder.build_all_steps()


class ExampleStepBuilder:
    """Builder class for constructing example steps based on available tools."""

    def __init__(self, available_tools: set[str], mode: str = 'agent') -> None:
        """Initialize the example step builder.

        Args:
            available_tools: Set of available tool names.
            mode: Interaction mode ('agent' or 'plan').

        """
        self.available_tools = available_tools
        self.mode = mode
        self.example = ''

    def build_all_steps(self) -> str:
        """Build all example steps.

        Returns:
            str: The complete example steps string.

        """
        self._add_directory_check_step()
        self._add_file_creation_step()
        self._add_server_run_step()
        self._add_page_view_step()
        self._add_server_kill_step()
        self._add_server_rerun_step()
        self._add_final_response_step()
        return self.example

    def _has_terminal_tool(self) -> bool:
        """Return True when any terminal command tool alias is present."""
        return any(
            key in self.available_tools
            for key in (TERMINAL_EXAMPLE_KEY, 'execute_bash', 'execute_powershell')
        )

    def _add_directory_check_step(self) -> None:
        """Add directory check step if terminal command tool is available."""
        if self._has_terminal_tool():
            self.example += TOOL_EXAMPLES[TERMINAL_EXAMPLE_KEY]['check_dir']

    def _add_file_creation_step(self) -> None:
        """Add file creation step when create is available."""
        if 'create' in self.available_tools:
            self.example += TOOL_EXAMPLES['create']['file']

    def _add_server_run_step(self) -> None:
        """Add server run step if terminal command tool is available."""
        if self._has_terminal_tool():
            self.example += TOOL_EXAMPLES[TERMINAL_EXAMPLE_KEY]['run_server']

    def _add_page_view_step(self) -> None:
        """Add page view step if browser is available."""
        if 'browser' in self.available_tools:
            self.example += TOOL_EXAMPLES['browser']['view_page']

    def _add_server_kill_step(self) -> None:
        """Add server kill step if terminal command tool is available."""
        if self._has_terminal_tool():
            self.example += TOOL_EXAMPLES[TERMINAL_EXAMPLE_KEY]['kill_server']

    def _add_server_rerun_step(self) -> None:
        """Add server rerun step if terminal command tool is available."""
        if self._has_terminal_tool():
            self.example += TOOL_EXAMPLES[TERMINAL_EXAMPLE_KEY]['run_server_again']

    def _add_final_response_step(self) -> None:
        """Add a plain-text final response example."""
        if not self.example:
            return
        if self.mode == 'plan':
            self.example += (
                '\nASSISTANT:\n'
                'Recommended plan:\n'
                '1. Create `src/templates/numbers.html` with table markup.\n'
                '2. Update `src/app.py` to render the template with numbers 1-10.\n'
                '3. Start the server on port 5000 and verify the page loads.\n'
            )
        else:
            self.example += (
                '\nASSISTANT:\n'
                'Implemented the Flask page so numbers 1-10 render in an HTML '
                'table, restarted the server on port 5000, and verified the page '
                'loads correctly. No follow-up is required unless you want sorting '
                'or pagination added next.\n'
            )


def _build_example_footer() -> str:
    """Build the footer section of the example."""
    return (
        '\n--------------------- END OF EXAMPLE ---------------------\n\n'
        'Do NOT assume the environment is the same as in the example above.\n\n'
        '--------------------- NEW TASK DESCRIPTION ---------------------\n'
    )


IN_CONTEXT_LEARNING_EXAMPLE_PREFIX = get_example_for_tools
IN_CONTEXT_LEARNING_EXAMPLE_SUFFIX = '\n--------------------- END OF NEW TASK DESCRIPTION ---------------------\n\nPLEASE follow the format strictly! IN THIS FALLBACK FORMAT, EMIT ONE TOOL CALL PER TOOL-CALL MESSAGE. WHEN COMPLETE, WRITE A PLAIN-TEXT FINAL RESPONSE.\n'
