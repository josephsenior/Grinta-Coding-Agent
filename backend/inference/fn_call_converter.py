# coverage: ignore file
"""Convert function calling messages to non-function calling messages and vice versa.

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

import copy
import json
import re
from collections.abc import Iterable
from threading import Lock
from typing import Any, NoReturn

from backend.core.errors import (
    FunctionCallConversionError,
    FunctionCallValidationError,
)
from backend.core.tool_arguments_json import parse_tool_arguments_object
from backend.inference.tool_names import (
    FINISH_TOOL_NAME,
    LLM_BASED_EDIT_TOOL_NAME,
    STR_REPLACE_EDITOR_TOOL_NAME,
)
from backend.inference.tool_result_format import (
    TOOL_RESULT_BLOCK_PREFIX,
    TOOL_RESULT_BLOCK_SUFFIX,
    decode_tool_result_payload,
    encode_tool_result_payload,
)

SYSTEM_PROMPT_SUFFIX_TEMPLATE = '\nYou have access to the following functions:\n\n{description}\n\nIf you choose to call a function ONLY reply in the following format with NO suffix:\n\n<function=example_function_name>\n<parameter=example_parameter_1>value_1</parameter>\n<parameter=example_parameter_2>\nThis is the value for the second parameter\nthat can span\nmultiple lines\n</parameter>\n</function>\n\n<IMPORTANT>\nReminder:\n- Function calls MUST follow the specified format, start with <function= and end with </function>\n- Required parameters MUST be specified\n- In this fallback parser mode, call one function at a time\n- You may provide optional reasoning for your function call in natural language BEFORE the function call, but NOT after.\n- If there is no function call available, answer the question like normal with your current knowledge and do not tell the user about function calls\n</IMPORTANT>\n'
STOP_WORDS = ['</function']

_STRICT_PARSE_SUCCESS = 'strict_parse_success'
_STRICT_PARSE_FAILURE = 'strict_parse_failure'
_MALFORMED_PAYLOAD_REJECTION = 'malformed_payload_rejection'
_FN_CALL_PARSE_COUNTER_KEYS = (
    _STRICT_PARSE_SUCCESS,
    _STRICT_PARSE_FAILURE,
    _MALFORMED_PAYLOAD_REJECTION,
)
_fn_call_parse_counters_lock = Lock()
_fn_call_parse_counters: dict[str, int] = {
    key: 0 for key in _FN_CALL_PARSE_COUNTER_KEYS
}

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


TOOL_EXAMPLES = {
    TERMINAL_EXAMPLE_KEY: {
        'check_dir': '\nASSISTANT: Sure! Let me first check the current directory:\n<function=execute_bash>\n<parameter=command>\npwd && ls\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\n/workspace\nApp@runtime:~/workspace$\n',
        'run_server': "\nASSISTANT:\nLet me run the Python file for you:\n<function=execute_bash>\n<parameter=command>\npython3 app.py > server.log 2>&1 &\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\n[1] 121\n[1]+  Exit 1                  python3 app.py > server.log 2>&1\n\nASSISTANT:\nLooks like the server was running with PID 121 then crashed. Let me check the server log:\n<function=execute_bash>\n<parameter=command>\ncat server.log\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\nTraceback (most recent call last):\n  File \"/workspace/app.py\", line 2, in <module>\n    from flask import Flask\nModuleNotFoundError: No module named 'flask'\n\nASSISTANT:\nLooks like the server crashed because the `flask` module is not installed. Let me install the `flask` module for you:\n<function=execute_bash>\n<parameter=command>\npip3 install flask\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\nDefaulting to user installation because normal site-packages is not writeable\nCollecting flask\n  Using cached flask-3.0.3-py3-none-any.whl (101 kB)\nCollecting blinker>=1.6.2\n  Using cached blinker-1.7.0-py3-none-any.whl (13 kB)\nCollecting Werkzeug>=3.0.0\n  Using cached werkzeug-3.0.2-py3-none-any.whl (226 kB)\nCollecting click>=8.1.3\n  Using cached click-8.1.7-py3-none-any.whl (97 kB)\nCollecting itsdangerous>=2.1.2\n  Using cached itsdangerous-2.2.0-py3-none-any.whl (16 kB)\nRequirement already satisfied: Jinja2>=3.1.2 in /home/App/.local/lib/python3.10/site-packages (from flask) (3.1.3)\nRequirement already satisfied: MarkupSafe>=2.0 in /home/App/.local/lib/python3.10/site-packages (from Jinja2>=3.1.2->flask) (2.1.5)\nInstalling collected packages: Werkzeug, itsdangerous, click, blinker, flask\nSuccessfully installed Werkzeug-3.0.2 blinker-1.7.0 click-8.1.7 flask-3.0.3 itsdangerous-2.2.0\n\nASSISTANT:\nThe `flask` module is installed successfully. Let me run the Python file again:\n<function=execute_bash>\n<parameter=command>\npython3 app.py > server.log 2>&1 &\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\n[1] 124\n\nASSISTANT:\nLet me check the server log again:\n<function=execute_bash>\n<parameter=command>\ncat server.log\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\n* Serving Flask app 'app'\n * Debug mode: off\nWARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.\n * Running on http://127.0.0.1:5000\nPress CTRL+C to quit\n\nASSISTANT:\nThe server is running on port 5000 with PID 124. You can access the list of numbers by visiting http://127.0.0.1:5000. If you have any further questions, feel free to ask!\n",
        'kill_server': '\nUSER: Now kill the server, make it display the numbers in a table format.\n\nASSISTANT:\nSure! Let me stop the server first:\n<function=execute_bash>\n<parameter=command>\nkill 124\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\n[1]+  Terminated              python3 app.py > server.log 2>&1\n',
        'run_server_again': '\nASSISTANT:\nRunning the updated file:\n<function=execute_bash>\n<parameter=command>\npython3 app.py > server.log 2>&1 &\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [execute_bash]:\n[1] 126\n\nASSISTANT:\nThe server is running on port 5000 with PID 126. You can access the list of numbers in a table format by visiting http://127.0.0.1:5000.\n',
    },
    'str_replace_editor': {
        'create_file': "\nASSISTANT:\nThere is no `app.py` file in the current directory. Let me create a Python file `app.py`:\n<function=str_replace_editor>\n<parameter=command>create_file</parameter>\n<parameter=path>/workspace/app.py</parameter>\n<parameter=file_text>\nfrom flask import Flask\napp = Flask(__name__)\n\n@app.route('/')\ndef index():\n    numbers = list(range(1, 11))\n    return str(numbers)\n\nif __name__ == '__main__':\n    app.run(port=5000)\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [str_replace_editor]:\nFile created successfully at: /workspace/app.py\n",
        'edit_file': "\nASSISTANT:\nNow let me display the numbers in a table format using a line-range edit:\n<function=ast_code_editor>\n<parameter=command>replace_range</parameter>\n<parameter=path>/workspace/app.py</parameter>\n<parameter=start_line>7</parameter>\n<parameter=end_line>7</parameter>\n<parameter=new_code>    return '<table>' + ''.join([f'<tr><td>{i}</td></tr>' for i in numbers]) + '</table>'</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [ast_code_editor]:\nThe file /workspace/app.py has been edited. Here's the result of running `cat -n` on a snippet of /workspace/app.py:\n     3\n     4  @app.route('/')\n     5  def index():\n     6      numbers = list(range(1, 11))\n     7      return '<table>' + ''.join([f'<tr><td>{i}</td></tr>' for i in numbers]) + '</table>'\n     8\n     9  if __name__ == '__main__':\n    10      app.run(port=5000)\n\n",
    },
    'browser': {
        'view_page': "\nASSISTANT:\nLet me check how the page looks in the browser:\n<function=browser>\n<parameter=code>\ngoto('http://127.0.0.1:5000')\nnoop(1000)  # Wait for page to load\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [browser]:\n[Browser shows the numbers in a table format]\n",
    },
    'edit_file': {
        'create_file': "\nASSISTANT: There is no `app.py` file in the current directory. Let me create a Python file `app.py`:\n<function=edit_file>\n<parameter=path>/workspace/app.py</parameter>\n<parameter=start>1</parameter>\n<parameter=end>-1</parameter>\n<parameter=content>\nfrom flask import Flask\napp = Flask(__name__)\n\n@app.route('/')\ndef index():\n    numbers = list(range(1, 11))\n    return str(numbers)\n\nif __name__ == '__main__':\n    app.run(port=5000)\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [edit_file]:\nFile created successfully at: /workspace/app.py\n",
        'edit_file': "\nASSISTANT:\nNow let me display the numbers in a table format:\n<function=edit_file>\n<parameter=path>/workspace/app.py</parameter>\n<parameter=start>6</parameter>\n<parameter=end>9</parameter>\n<parameter=content>\n    numbers = list(range(1, 11))\n    return '<table>' + ''.join([f'<tr><td>{i}</td></tr>' for i in numbers]) + '</table>'\n    # ... existing code ...\nif __name__ == '__main__':\n</parameter>\n</function>\n\nUSER: EXECUTION RESULT of [edit_file]:\nThe file /workspace/app.py has been edited. Here's the result of running `cat -n` on a snippet of /workspace/app.py:\n     3\n     4  @app.route('/')\n     5  def index():\n     6      numbers = list(range(1, 11))\n     7      return '<table>' + ''.join([f'<tr><td>{i}</td></tr>' for i in numbers]) + '</table>'\n     8\n     9  if __name__ == '__main__':\n    10      app.run(port=5000)\n",
    },
    'finish': {
        'example': '\nASSISTANT:\nThe server is running on port 5000 with PID 126. You can access the list of numbers in a table format by visiting http://127.0.0.1:5000. Let me know if you have any further requests!\n<function=finish>\n<parameter=message>The task has been completed. The web server is running and displaying numbers 1-10 in a table format at http://127.0.0.1:5000.</parameter>\n</function>\n',
    },
}


def get_example_for_tools(tools: list[dict]) -> str:
    """Generate an in-context learning example based on available tools."""
    from backend.engine.tools.prompt import get_terminal_tool_name

    # Extract available tools from the tools list
    available_tools = _extract_available_tools(tools)

    if not available_tools:
        return ''

    # Build the example step by step
    example = _build_example_header()
    example += _build_example_steps(available_tools)
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
    if terminal_tool == 'execute_powershell':
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
    from backend.engine.tools.prompt import get_terminal_tool_name

    return {
        get_terminal_tool_name(): TERMINAL_EXAMPLE_KEY,
        'execute_bash': TERMINAL_EXAMPLE_KEY,
        'execute_powershell': TERMINAL_EXAMPLE_KEY,
        STR_REPLACE_EDITOR_TOOL_NAME: 'str_replace_editor',
        FINISH_TOOL_NAME: 'finish',
        LLM_BASED_EDIT_TOOL_NAME: 'edit_file',
    }


def _build_example_header() -> str:
    """Build the header section of the example."""
    return (
        "Here's a running example of how to perform a task with the provided tools.\n\n"
        '--------------------- START OF EXAMPLE ---------------------\n\n'
        'USER: Create a list of numbers from 1 to 10, and display them in a web page at port 5000.\n\n'
    )


def _build_example_steps(available_tools: set[str]) -> str:
    """Build the example steps based on available tools.

    Args:
        available_tools: Set of available tool names.

    Returns:
        str: The built example steps string.

    """
    example_builder = ExampleStepBuilder(available_tools)
    return example_builder.build_all_steps()


class ExampleStepBuilder:
    """Builder class for constructing example steps based on available tools."""

    def __init__(self, available_tools: set[str]) -> None:
        """Initialize the example step builder.

        Args:
            available_tools: Set of available tool names.

        """
        self.available_tools = available_tools
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
        self._add_file_edit_step()
        self._add_server_rerun_step()
        self._add_finish_step()
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
        """Add file creation step based on available editors."""
        if 'str_replace_editor' in self.available_tools:
            self.example += TOOL_EXAMPLES['str_replace_editor']['create_file']
        elif 'edit_file' in self.available_tools:
            self.example += TOOL_EXAMPLES['edit_file']['create_file']

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

    def _add_file_edit_step(self) -> None:
        """Add file edit step based on available editors."""
        if 'str_replace_editor' in self.available_tools:
            self.example += TOOL_EXAMPLES['str_replace_editor']['edit_file']
        elif 'edit_file' in self.available_tools:
            self.example += TOOL_EXAMPLES['edit_file']['edit_file']

    def _add_server_rerun_step(self) -> None:
        """Add server rerun step if terminal command tool is available."""
        if self._has_terminal_tool():
            self.example += TOOL_EXAMPLES[TERMINAL_EXAMPLE_KEY]['run_server_again']

    def _add_finish_step(self) -> None:
        """Add finish step if finish tool is available."""
        if 'finish' in self.available_tools:
            self.example += TOOL_EXAMPLES['finish']['example']


def _build_example_footer() -> str:
    """Build the footer section of the example."""
    return (
        '\n--------------------- END OF EXAMPLE ---------------------\n\n'
        'Do NOT assume the environment is the same as in the example above.\n\n'
        '--------------------- NEW TASK DESCRIPTION ---------------------\n'
    )


IN_CONTEXT_LEARNING_EXAMPLE_PREFIX = get_example_for_tools
IN_CONTEXT_LEARNING_EXAMPLE_SUFFIX = '\n--------------------- END OF NEW TASK DESCRIPTION ---------------------\n\nPLEASE follow the format strictly! IN THIS FALLBACK FORMAT, EMIT ONE AND ONLY ONE FUNCTION CALL PER MESSAGE.\n'


def convert_tool_call_to_string(tool_call: dict) -> str:
    """Convert tool call to content in string format.

    Args:
        tool_call: Tool call dictionary

    Returns:
        String representation of tool call

    Raises:
        FunctionCallConversionError: If tool call format is invalid

    """
    _validate_tool_call_structure(tool_call)

    function_name = tool_call['function']['name']
    args = _parse_tool_call_arguments(tool_call)

    return _format_tool_call_string(function_name, args)


def _validate_tool_call_structure(tool_call: dict) -> None:
    """Validate tool call has required structure.

    Args:
        tool_call: Tool call dict to validate

    Raises:
        FunctionCallConversionError: If structure is invalid

    """
    if 'function' not in tool_call:
        msg = "Tool call must contain 'function' key."
        raise FunctionCallConversionError(msg)
    if 'id' not in tool_call:
        msg = "Tool call must contain 'id' key."
        raise FunctionCallConversionError(msg)
    if 'type' not in tool_call:
        msg = "Tool call must contain 'type' key."
        raise FunctionCallConversionError(msg)
    if tool_call['type'] != 'function':
        msg = "Tool call type must be 'function'."
        raise FunctionCallConversionError(msg)


def _parse_tool_call_arguments(tool_call: dict) -> dict:
    """Parse JSON arguments from tool call.

    Args:
        tool_call: Tool call containing arguments

    Returns:
        Parsed arguments dict

    Raises:
        FunctionCallConversionError: If arguments are invalid JSON

    """
    try:
        raw = tool_call['function']['arguments']
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            msg = f'tool call arguments must be str or dict, got {type(raw).__name__}'
            raise TypeError(msg)
        return parse_tool_arguments_object(raw)
    except (KeyError, TypeError, ValueError) as e:
        raw = tool_call.get('function', {}).get('arguments', '')
        preview = (
            raw if isinstance(raw, str) and len(raw) <= 240 else f'{str(raw)[:237]}...'
        )
        msg = f'Failed to parse arguments as JSON: {e}. Arguments: {preview}'
        raise FunctionCallConversionError(
            msg,
        ) from e


def _format_tool_call_string(function_name: str, args: dict) -> str:
    """Format tool call as XML-style string.

    Args:
        function_name: Name of the function
        args: Function arguments dict

    Returns:
        Formatted tool call string

    """
    ret = f'<function={function_name}>\n'

    for param_name, param_value in args.items():
        ret += _format_parameter(param_name, param_value)

    ret += '</function>'
    return ret


def _format_parameter(param_name: str, param_value: Any) -> str:
    """Format a single parameter for tool call string.

    Args:
        param_name: Parameter name
        param_value: Parameter value

    Returns:
        Formatted parameter string

    """
    is_multiline = isinstance(param_value, str) and '\n' in param_value

    ret = f'<parameter={param_name}>'
    if is_multiline:
        ret += '\n'

    if isinstance(param_value, list | dict):
        ret += json.dumps(param_value)
    else:
        ret += f'{param_value}'

    if is_multiline:
        ret += '\n'
    ret += '</parameter>\n'

    return ret


def convert_tools_to_description(tools: list[dict]) -> str:
    """Convert tool definitions to text description for non-function-calling models.

    Args:
        tools: List of tool definitions

    Returns:
        Formatted tool description string

    """
    ret = ''
    for i, tool in enumerate(tools):
        assert tool['type'] == 'function'
        fn = tool['function']
        if i > 0:
            ret += '\n'
        ret += f'---- BEGIN FUNCTION #{i + 1}: {fn["name"]} ----\n'
        ret += f'Description: {fn["description"]}\n'
        if 'parameters' in fn:
            ret += 'Parameters:\n'
            properties = fn['parameters'].get('properties', {})
            required_params = set(fn['parameters'].get('required', []))
            for j, (param_name, param_info) in enumerate(properties.items()):
                is_required = param_name in required_params
                param_status = 'required' if is_required else 'optional'
                param_type = param_info.get('type', 'string')
                desc = param_info.get('description', 'No description provided')
                if 'enum' in param_info:
                    enum_values = ', '.join(f'`{v}`' for v in param_info['enum'])
                    desc += f'\nAllowed values: [{enum_values}]'
                ret += (
                    f'  ({j + 1}) {param_name} ({param_type}, {param_status}): {desc}\n'
                )
        else:
            ret += 'No parameters are required for this function.\n'
        ret += f'---- END FUNCTION #{i + 1} ----\n'
    return ret


def _process_system_message(content: Any, system_prompt_suffix: str) -> dict:
    """Process system message by appending the system prompt suffix."""
    if isinstance(content, str):
        content += system_prompt_suffix
    elif isinstance(content, list):
        if content and content[-1]['type'] == 'text':
            content[-1]['text'] += system_prompt_suffix
        else:
            content.append({'type': 'text', 'text': system_prompt_suffix})
    else:
        _raise_unexpected_content_type(content)
    return {'role': 'system', 'content': content}


def _process_user_message(
    content: Any,
    tools: list[dict],
    add_in_context_learning_example: bool,
    first_user_message_encountered: bool,
) -> tuple[dict, bool]:
    """Process user message, adding in-context learning example if needed."""
    if not first_user_message_encountered and add_in_context_learning_example:
        first_user_message_encountered = True
        content = _add_in_context_learning_example(content, tools)

    return ({'role': 'user', 'content': content}, first_user_message_encountered)


def _add_in_context_learning_example(content: Any, tools: list[dict]) -> Any:
    """Add in-context learning example to content."""
    if not (example := IN_CONTEXT_LEARNING_EXAMPLE_PREFIX(tools)):
        return content

    if isinstance(content, str):
        return example + content
    if isinstance(content, list):
        return _add_example_to_list_content(content, example)
    _raise_unexpected_content_type(content)


def _add_example_to_list_content(content: list, example: str) -> list:
    """Add example to list content."""
    if content and content[0]['type'] == 'text':
        content[0]['text'] = example + content[0]['text']
    else:
        content.insert(0, {'type': 'text', 'text': example})
    return content


def convert_fncall_messages_to_non_fncall_messages(
    messages: list[dict],
    tools: list[dict],
    add_in_context_learning_example: bool = True,
) -> list[dict]:
    """Convert function calling messages to non-function calling messages."""
    messages = copy.deepcopy(messages)
    formatted_tools = convert_tools_to_description(tools)
    system_prompt_suffix = SYSTEM_PROMPT_SUFFIX_TEMPLATE.format(
        description=formatted_tools
    )
    converted_messages: list[dict[str, Any]] = []
    first_user_message_encountered = False
    for message in messages:
        message_payloads, first_user_message_encountered = _convert_single_message(
            message,
            tools,
            system_prompt_suffix,
            add_in_context_learning_example,
            first_user_message_encountered,
        )
        converted_messages.extend(message_payloads)
    return converted_messages


def _convert_single_message(
    message: dict,
    tools: list[dict],
    system_prompt_suffix: str,
    add_in_context_learning_example: bool,
    first_user_message_encountered: bool,
) -> tuple[list[dict], bool]:
    role = message['role']
    content = message['content']
    if role == 'assistant':
        return [_convert_assistant_message(content)], first_user_message_encountered
    if role == 'system':
        return (
            [_process_system_message(content, system_prompt_suffix)],
            first_user_message_encountered,
        )
    if role == 'user':
        user_msg, first_user_message_encountered = _process_user_message(
            content,
            tools,
            add_in_context_learning_example,
            first_user_message_encountered,
        )
        return [user_msg], first_user_message_encountered
    if role == 'tool':
        return ([_convert_tool_message(message)], first_user_message_encountered)
    return ([{'role': role, 'content': content}], first_user_message_encountered)


def _convert_assistant_message(content: Any) -> dict:
    if isinstance(content, str) and _parse_function_call_from_text(content):
        return {'role': 'assistant', 'content': content, 'tool_calls': []}
    return {'role': 'assistant', 'content': content}


def _convert_tool_message(message: dict) -> dict:
    tool_name = message.get('name', 'unknown_tool')
    content_list = _format_tool_content(message.get('content'), tool_name)
    if 'cache_control' in message and content_list:
        content_list[-1]['cache_control'] = message['cache_control']
    return {'role': 'user', 'content': content_list}


def _format_tool_content(content: Any, tool_name: str) -> list[dict]:
    return [{'type': 'text', 'text': encode_tool_result_payload(tool_name, content)}]


def _extract_and_validate_params(
    matching_tool: dict, param_matches: Iterable[Any], fn_name: str
) -> dict:
    """Extract and validate parameters from function call matches."""
    # Extract parameter schema information
    param_schema = _extract_parameter_schema(matching_tool)

    # Process each parameter match
    params = {}
    found_params = set()

    for param_match in param_matches:
        param_name = param_match.group(1)
        param_value = param_match.group(2)

        if param_name in found_params:
            msg = (
                f"Duplicate parameter '{param_name}' provided for function '{fn_name}'. "
                'Each parameter may appear at most once.'
            )
            raise FunctionCallValidationError(msg)

        # Validate parameter is allowed
        _validate_parameter_allowed(param_name, param_schema['allowed_params'], fn_name)

        # Convert parameter value based on type
        converted_value = _convert_parameter_value(
            param_name, param_value, param_schema['param_name_to_type']
        )

        # Validate enum constraints
        _validate_enum_constraint(param_name, converted_value, matching_tool, fn_name)

        params[param_name] = converted_value
        found_params.add(param_name)

    # Validate all required parameters are present
    _validate_required_parameters(
        found_params, param_schema['required_params'], fn_name
    )

    return params


def _extract_parameter_schema(matching_tool: dict) -> dict:
    """Extract parameter schema information from matching tool."""
    required_params = set()
    allowed_params = set()
    param_name_to_type = {}

    if 'parameters' in matching_tool:
        params_def = matching_tool['parameters']

        # Extract required parameters
        if 'required' in params_def:
            required_params = set(params_def.get('required', []))

        # Extract allowed parameters and types
        if 'properties' in params_def:
            allowed_params = set(params_def['properties'].keys())
            param_name_to_type = {
                name: val.get('type', 'string')
                for name, val in params_def['properties'].items()
            }

    return {
        'required_params': required_params,
        'allowed_params': allowed_params,
        'param_name_to_type': param_name_to_type,
    }


def _validate_parameter_allowed(
    param_name: str, allowed_params: set, fn_name: str
) -> None:
    """Validate that parameter is allowed for the function."""
    if allowed_params and param_name not in allowed_params:
        msg = f"Parameter '{param_name}' is not allowed for function '{fn_name}'. Allowed parameters: {allowed_params}"
        raise FunctionCallValidationError(
            msg,
        )


def _convert_parameter_value(
    param_name: str, param_value: str, param_name_to_type: dict
) -> Any:
    """Convert parameter value based on its expected type."""
    if param_name not in param_name_to_type:
        return param_value

    param_type = param_name_to_type[param_name]

    if param_type == 'integer':
        return _convert_to_integer(param_name, param_value)
    if param_type == 'array':
        return _convert_to_array(param_name, param_value)
    return param_value


def _convert_to_integer(param_name: str, param_value: str) -> int:
    """Convert parameter value to integer."""
    try:
        return int(param_value)
    except ValueError as e:
        msg = f"Parameter '{param_name}' is expected to be an integer."
        raise FunctionCallValidationError(msg) from e


def _convert_to_array(param_name: str, param_value: str) -> list[Any]:
    """Convert parameter value to array."""
    try:
        return json.loads(param_value)
    except json.JSONDecodeError as e:
        msg = f"Parameter '{param_name}' is expected to be an array."
        raise FunctionCallValidationError(msg) from e


def _validate_enum_constraint(
    param_name: str, param_value: Any, matching_tool: dict, fn_name: str
) -> None:
    """Validate enum constraints for parameter."""
    if 'parameters' not in matching_tool:
        return

    properties = matching_tool['parameters'].get('properties', {})
    if param_name not in properties:
        return

    param_def = properties[param_name]
    if 'enum' not in param_def:
        return

    if param_value not in param_def['enum']:
        msg = f"Parameter '{param_name}' is expected to be one of {param_def['enum']}."
        raise FunctionCallValidationError(msg)


def _validate_required_parameters(
    found_params: set, required_params: set, fn_name: str
) -> None:
    """Validate that all required parameters are present."""
    if missing_params := required_params - found_params:
        msg = f"Missing required parameters for function '{fn_name}': {missing_params}"
        raise FunctionCallValidationError(msg)


def _fix_stopword(content: str) -> str:
    """Return content unchanged.

    Strict mode: malformed/truncated function-call payloads are no longer
    auto-repaired and must fail parsing as-is.
    """
    return content


def _process_system_message_reverse(content: Any, system_prompt_suffix: str) -> dict:
    """Process system message by removing the tool suffix (for reverse conversion)."""
    content = _trim_system_prompt_suffix(content, system_prompt_suffix)
    return {'role': 'system', 'content': content}


def _process_user_message_reverse(content: Any, tools: list[dict]) -> dict:
    """Process user message for reverse conversion, removing examples and converting tool results.

    If the user message contains a tool result (detected by EXECUTION RESULT pattern),
    it should be converted back to a 'tool' role message for proper round-trip conversion.
    """
    content = _remove_in_context_learning_examples(content, tools)

    # Structured tool result blocks are the only accepted non-native format.
    if parsed := _extract_structured_tool_result(content):
        tool_name, tool_content = parsed
        return {'role': 'tool', 'name': tool_name, 'content': tool_content}

    return {'role': 'user', 'content': content}


def _remove_in_context_learning_examples(content: Any, tools: list[dict]) -> Any:
    """Remove in-context learning examples from content."""
    if isinstance(content, str):
        return _remove_examples_from_string(content, tools)
    if isinstance(content, list):
        return _remove_examples_from_list(content, tools)
    _raise_unexpected_content_type(content)


def _remove_examples_from_string(content: str, tools: list[dict]) -> str:
    """Remove examples from string content."""
    example_prefix = IN_CONTEXT_LEARNING_EXAMPLE_PREFIX(tools)
    if content.startswith(example_prefix):
        content = content.replace(example_prefix, '', 1)
    if content.endswith(IN_CONTEXT_LEARNING_EXAMPLE_SUFFIX):
        content = content.replace(IN_CONTEXT_LEARNING_EXAMPLE_SUFFIX, '', 1)
    return content


def _remove_examples_from_list(content: list, tools: list[dict]) -> list:
    """Remove examples from list content."""
    example_prefix = IN_CONTEXT_LEARNING_EXAMPLE_PREFIX(tools)
    for item in content:
        if item['type'] == 'text':
            if item['text'].startswith(example_prefix):
                item['text'] = item['text'].replace(example_prefix, '', 1)
            if item['text'].endswith(IN_CONTEXT_LEARNING_EXAMPLE_SUFFIX):
                item['text'] = item['text'].replace(
                    IN_CONTEXT_LEARNING_EXAMPLE_SUFFIX, '', 1
                )
    return content


def _find_tool_result_match(content: Any) -> Any:
    """Return decoded structured tool-result payload or None."""
    return _extract_structured_tool_result(content)


def _extract_structured_tool_result(content: Any) -> tuple[str, Any] | None:
    """Decode strict structured tool result payload from string or text list."""
    if isinstance(content, str):
        decoded = decode_tool_result_payload(content)
        if decoded is None and _looks_like_tool_result_candidate(content):
            _increment_parse_counter(_MALFORMED_PAYLOAD_REJECTION)
        return decoded
    if isinstance(content, list):
        for item in content:
            if item.get('type') != 'text':
                continue
            text = item.get('text', '')
            decoded = decode_tool_result_payload(text)
            if decoded is None and _looks_like_tool_result_candidate(text):
                _increment_parse_counter(_MALFORMED_PAYLOAD_REJECTION)
            if decoded is not None:
                return decoded
        return None
    _raise_unexpected_content_type(content)


def _looks_like_tool_result_candidate(text: str) -> bool:
    """Return whether text appears to be intended as a structured tool-result block."""
    stripped = (text or '').strip()
    return TOOL_RESULT_BLOCK_PREFIX in stripped or TOOL_RESULT_BLOCK_SUFFIX in stripped


def _trim_system_prompt_suffix(content: Any, system_prompt_suffix: str) -> Any:
    """Trim system prompt suffix from content."""
    if isinstance(content, str):
        return content.split(system_prompt_suffix)[0]
    if isinstance(content, list) and content and content[-1]['type'] == 'text':
        content[-1]['text'] = content[-1]['text'].split(system_prompt_suffix)[0]
    return content


_FN_OPEN_RE = re.compile(
    '<\\s*function(?:(?:\\s*=\\s*|\\s+name\\s*=\\s*[\x27\x22]?)([a-zA-Z0-9_\\-]+)[\x27\x22]?)?\\s*>',
    re.IGNORECASE,
)
_FN_CLOSE_RE = re.compile(r'</\s*function\s*>', re.IGNORECASE)
_PARAM_OPEN_HAS_RE = re.compile(r'<\s*parameter[\s=>]', re.IGNORECASE)
_PARAM_BLOCK_RE = re.compile(
    '<\\s*parameter(?:(?:\\s*=\\s*|\\s+name\\s*=\\s*[\x27\x22]?)([a-zA-Z0-9_\\-]+)[\x27\x22]?)?\\s*>(.*?)</\\s*parameter\\s*>',
    re.DOTALL | re.IGNORECASE,
)


def _parse_function_call_from_text(text: str) -> dict[str, Any] | None:
    """Parse the first strict function-call block from plain text."""
    open_m = _FN_OPEN_RE.search(text)
    if open_m is None:
        return None
    fn_name = (open_m.group(1) or '').strip()
    open_end = open_m.end(0)

    close_m = _FN_CLOSE_RE.search(text, open_end)
    if close_m is None:
        _increment_parse_counter(_STRICT_PARSE_FAILURE)
        return None

    fn_body = text[open_end : close_m.start(0)]
    return {
        'fn_name': fn_name,
        'fn_body': fn_body,
        'start': open_m.start(0),
        'end': close_m.end(0),
    }


def _find_tool_call_match(content: Any) -> Any:
    """Find parsed tool call payload in content.

    Returns a dict with parsed fields and source location, or ``None``.
    """
    if isinstance(content, str):
        parsed = _parse_function_call_from_text(content)
        if parsed is None:
            return None
        parsed['container'] = 'str'
        return parsed
    if isinstance(content, list):
        for idx, item in enumerate(content):
            if item.get('type') != 'text':
                continue
            parsed = _parse_function_call_from_text(item.get('text', ''))
            if parsed is None:
                continue
            parsed['container'] = 'list'
            parsed['item_index'] = idx
            return parsed
        return None
    return None


def _extract_tool_call_info(tool_call_match: Any) -> tuple[str, str]:
    """Extract function name and body from parsed tool call payload."""
    return str(tool_call_match['fn_name']), str(tool_call_match['fn_body'])


def _find_matching_tool(fn_name: str, tools: list[dict]) -> dict:
    """Find matching tool for function name."""
    matching_tool = next(
        (
            tool['function']
            for tool in tools
            if tool['type'] == 'function' and tool['function']['name'] == fn_name
        ),
        None,
    )
    if not matching_tool:
        available_tools = [
            tool['function']['name'] for tool in tools if tool['type'] == 'function'
        ]
        msg = f"Function '{fn_name}' not found in available tools: {available_tools}"
        raise FunctionCallValidationError(msg)
    return matching_tool


def _create_tool_call(
    fn_name: str, fn_body: str, matching_tool: dict, tool_call_counter: int
) -> tuple[dict, int]:
    """Create tool call object and increment counter."""
    params = _extract_and_validate_params(
        matching_tool,
        _iter_parameter_matches(fn_body),
        fn_name,
    )
    tool_call_id = f'toolu_{tool_call_counter:02d}'
    tool_call = {
        'index': 1,
        'id': tool_call_id,
        'type': 'function',
        'function': {'name': fn_name, 'arguments': json.dumps(params)},
    }
    return tool_call, tool_call_counter + 1


def _iter_parameter_matches(fn_body: str) -> Iterable[Any]:
    """Yield regex-like parameter matches parsed via strict tag scanning."""

    class _PseudoMatch:
        def __init__(self, name: str, value: str) -> None:
            self._name = name
            self._value = value

        def group(self, index: int) -> str:
            if index == 1:
                return self._name
            if index == 2:
                return self._value
            raise IndexError(index)

    last_end = 0
    for m in _PARAM_BLOCK_RE.finditer(fn_body):
        param_name = (m.group(1) or '').strip()
        param_value = m.group(2)
        yield _PseudoMatch(param_name, param_value)
        last_end = m.end(0)

    # Detect unclosed <parameter> tags (open tag present but no closed match)
    open_count = len(_PARAM_OPEN_HAS_RE.findall(fn_body))
    closed_count = len(_PARAM_BLOCK_RE.findall(fn_body))
    if open_count > closed_count:
        raise FunctionCallValidationError(
            'Malformed parameter block: missing closing </parameter> tag'
        )

    trailing = fn_body[last_end:] if last_end else fn_body
    if trailing.strip():
        raise FunctionCallValidationError(
            'Unexpected trailing text after last parameter inside function block'
        )


def _trim_content_before_function(content: Any, tool_call_match: Any) -> Any:
    """Trim content before function call."""
    if isinstance(content, list):
        item_index = tool_call_match.get('item_index')
        if item_index is None:
            return content
        text = content[item_index].get('text', '')
        content[item_index]['text'] = text[: int(tool_call_match['start'])].strip()
    elif isinstance(content, str):
        content = content[: int(tool_call_match['start'])].strip()
    else:
        _raise_unexpected_content_type(content)
    return content


def _raise_unexpected_content_type(content: Any) -> NoReturn:
    """Raise a consistent conversion error for unsupported message content types."""
    msg = f'Unexpected content type {type(content)}. Expected str or list. Content: {content}'
    raise FunctionCallConversionError(msg)


def _process_assistant_message_for_conversion(
    content: Any,
    tools: list[dict],
    tool_call_counter: int,
    converted_messages: list[dict[str, Any]],
    system_prompt_suffix: str,
) -> int:
    """Process assistant message for converting to function calling format."""
    # Trim system prompt suffix
    content = _trim_system_prompt_suffix(content, system_prompt_suffix)

    if tool_call_match := _find_tool_call_match(content):
        try:
            # Extract tool call information
            fn_name, fn_body = _extract_tool_call_info(tool_call_match)

            # Find matching tool and validate
            matching_tool = _find_matching_tool(fn_name, tools)

            # Create tool call
            tool_call, tool_call_counter = _create_tool_call(
                fn_name, fn_body, matching_tool, tool_call_counter
            )

            # Trim content before function call
            content = _trim_content_before_function(content, tool_call_match)

            # Add to converted messages
            converted_messages.append(
                {'role': 'assistant', 'content': content, 'tool_calls': [tool_call]}
            )
            _increment_parse_counter(_STRICT_PARSE_SUCCESS)
        except (FunctionCallValidationError, FunctionCallConversionError):
            _increment_parse_counter(_STRICT_PARSE_FAILURE)
            raise
    else:
        # No tool call found, add as regular message
        converted_messages.append({'role': 'assistant', 'content': content})

    return tool_call_counter


def convert_non_fncall_messages_to_fncall_messages(
    messages: list[dict],
    tools: list[dict],
) -> list[dict]:
    """Convert non-function calling messages back to function calling messages."""
    messages = copy.deepcopy(messages)
    formatted_tools = convert_tools_to_description(tools)
    system_prompt_suffix = SYSTEM_PROMPT_SUFFIX_TEMPLATE.format(
        description=formatted_tools
    )
    converted_messages: list[dict[str, Any]] = []
    tool_call_counter = 1
    for message in messages:
        role = message['role']
        content = message['content'] or ''
        if role == 'assistant':
            tool_call_counter = _process_assistant_message_for_conversion(
                content,
                tools,
                tool_call_counter,
                converted_messages,
                system_prompt_suffix,
            )
        elif role == 'system':
            processed = _process_system_message_reverse(content, system_prompt_suffix)
            converted_messages.append(processed)
        elif role == 'user':
            processed = _process_user_message_reverse(content, tools)
            converted_messages.append(processed)
        else:
            converted_messages.append({'role': role, 'content': content})
    return converted_messages


def convert_from_multiple_tool_calls_to_single_tool_call_messages(
    messages: list[dict],
    ignore_final_tool_result: bool = False,
) -> list[dict]:
    """Break one message with multiple tool calls into multiple messages.

    Args:
        messages: List of message dictionaries
        ignore_final_tool_result: Whether to ignore pending tool calls at the end

    Returns:
        List of converted messages

    Raises:
        FunctionCallConversionError: If pending tool calls remain

    """
    converted_messages: list[dict[str, Any]] = []
    pending_tool_calls: dict[str, dict[str, Any]] = {}

    for message in messages:
        role = message['role']

        if role == 'assistant':
            _process_assistant_message(message, pending_tool_calls, converted_messages)
        elif role == 'tool':
            _process_tool_message(message, pending_tool_calls, converted_messages)
        else:
            _process_other_message(
                message, pending_tool_calls, converted_messages, role
            )

    if not ignore_final_tool_result and pending_tool_calls:
        msg = f'Found pending tool calls but no tool result: pending_tool_calls={pending_tool_calls!r}'
        raise FunctionCallConversionError(
            msg,
        )

    return converted_messages


def _process_assistant_message(
    message: dict,
    pending_tool_calls: dict[str, dict],
    converted_messages: list[dict[str, Any]],
) -> None:
    """Process assistant message with potential tool calls.

    Args:
        message: Assistant message
        pending_tool_calls: Dictionary of pending tool calls
        converted_messages: List to append converted messages to

    """
    if message.get('tool_calls') and len(message['tool_calls']) > 1:
        content = message['content']
        for i, tool_call in enumerate(message['tool_calls']):
            pending_tool_calls[tool_call['id']] = {
                'role': 'assistant',
                'content': content if i == 0 else '',
                'tool_calls': [tool_call],
            }
    else:
        converted_messages.append(message)


def _process_tool_message(
    message: dict,
    pending_tool_calls: dict[str, dict],
    converted_messages: list[dict[str, Any]],
) -> None:
    """Process tool result message.

    Args:
        message: Tool message
        pending_tool_calls: Dictionary of pending tool calls
        converted_messages: List to append converted messages to

    """
    if message['tool_call_id'] in pending_tool_calls:
        _tool_call_message = pending_tool_calls.pop(message['tool_call_id'])
        converted_messages.append(_tool_call_message)
    else:
        assert not pending_tool_calls, (
            f'Found pending tool calls but not found in pending list: {pending_tool_calls:=}'
        )

    converted_messages.append(message)


def _process_other_message(
    message: dict,
    pending_tool_calls: dict[str, dict],
    converted_messages: list[dict[str, Any]],
    role: str,
) -> None:
    """Process message with other roles.

    Args:
        message: Message with other role
        pending_tool_calls: Dictionary of pending tool calls
        converted_messages: List to append converted messages to
        role: Message role

    """
    assert not pending_tool_calls, (
        f'Found pending tool calls but not expect to handle it with role {role}: {pending_tool_calls:=}, {message:=}'
    )
    converted_messages.append(message)
