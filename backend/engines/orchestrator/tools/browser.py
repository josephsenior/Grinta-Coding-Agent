"""Browser interaction tool used by CodeAct for high-level navigation."""

from __future__ import annotations

from browsergym.core.action.highlevel import HighLevelActionSet

from backend.engines.orchestrator.tools.common import (
    create_tool_definition,
    get_security_risk_param,
)
from backend.llm.tool_names import BROWSER_TOOL_NAME
from backend.engines.orchestrator.contracts import ChatCompletionToolParam

_browser_action_space = HighLevelActionSet(
    subsets=["bid", "nav"], strict=False, multiaction=True
)
_BROWSER_DESCRIPTION = (
    "Interact with the browser using Python code. Use it ONLY when you need to interact with a webpage.\n\n"
    'See the description of "code" parameter for more details.\n\n'
    "Multiple actions can be provided at once, but will be executed sequentially without any feedback from the page.\n"
    "More than 2-3 actions usually leads to failure or unexpected behavior. Example:\n"
    "fill('a12', 'example with \"quotes\"')\n"
    "click('a51')\n"
    "click('48', button='middle', modifiers=['Shift'])\n\n"
    "You can also use the browser to view pdf, png, jpg files.\n"
    "You should first check the content of /tmp/oh-server-url to get the server url, "
    'and then use it to view the file by `goto("{server_url}/view?path={absolute_file_path}")`.\n'
    'For example: `goto("http://localhost:8000/view?path=/workspace/test_document.pdf")`\n'
    "Note: The file should be downloaded to the local machine first before using the browser to view it.\n\n"
    "CRITICAL: When navigating to localhost URLs (especially newly created servers), "
    "you MUST wait for the server to be ready first. Failure to do so will result in "
    "chrome-error://chromewebdata/ pages. ALWAYS use this exact pattern for localhost navigation:\n\n"
    "```python\n"
    "import time\n"
    "import requests\n\n"
    "# Extract URL from goto() call\n"
    'url = "http://localhost:PORT"  # The URL you want to navigate to\n\n'
    "# Wait for server readiness\n"
    'print(f"🔍 Checking if server at {{url}} is ready...")\n'
    "max_wait = 30\n"
    "server_ready = False\n\n"
    "for i in range(max_wait):\n"
    "    try:\n"
    "        response = requests.head(url, timeout=5, allow_redirects=True)\n"
    "        if response.status_code < 500:\n"
    '            print(f"✅ Server is ready! Status: {{response.status_code}}")\n'
    "            server_ready = True\n"
    "            break\n"
    "    except Exception as e:\n"
    '        print(f"⏳ Server not ready yet ({{i+1}}/{{max_wait}}): {{e}}")\n'
    "    time.sleep(1)\n\n"
    "if not server_ready:\n"
    '    print(f"⚠️ Server not ready after {{max_wait}} seconds, proceeding anyway...")\n\n'
    "# Now navigate to the URL\n"
    "goto(url)\n"
    "```\n\n"
    "This pattern MUST be used for ALL localhost URLs to prevent navigation errors.\n"
)
_BROWSER_TOOL_DESCRIPTION = (
    "\nThe following 15 functions are available. Nothing else is supported.\n\n"
    "goto(url: str)\n"
    "    Description: Navigate to a url.\n"
    "    Examples:\n"
    "        goto('http://www.example.com')\n\n"
    "go_back()\n"
    "    Description: Navigate to the previous page in history.\n"
    "    Examples:\n"
    "        go_back()\n\n"
    "go_forward()\n"
    "    Description: Navigate to the next page in history.\n"
    "    Examples:\n"
    "        go_forward()\n\n"
    "noop(wait_ms: float = 1000)\n"
    "    Description: Do nothing, and optionally wait for the given time (in milliseconds).\n"
    "    You can use this to get the current page content and/or wait for the page to load.\n"
    "    Examples:\n"
    "        noop()\n\n"
    "        noop(500)\n\n"
    "scroll(delta_x: float, delta_y: float)\n"
    "    Description: Scroll horizontally and vertically. Amounts in pixels, positive for "
    "right or down scrolling, negative for left or up scrolling. Dispatches a wheel event.\n"
    "    Examples:\n"
    "        scroll(0, 200)\n\n"
    "        scroll(-50.2, -100.5)\n\n"
    "fill(bid: str, value: str)\n"
    "    Description: Fill out a form field. It focuses the element and triggers an input event "
    "with the entered text. It works for <input>, <textarea> and [contenteditable] elements.\n"
    "    Examples:\n"
    "        fill('237', 'example value')\n\n"
    "        fill('45', 'multi-line\\nexample')\n\n"
    "        fill('a12', 'example with \"quotes\"')\n\n"
    "select_option(bid: str, options: str | list[str])\n"
    "    Description: Select one or multiple options in a <select> element. "
    "You can specify option value or label to select. Multiple options can be selected.\n"
    "    Examples:\n"
    "        select_option('a48', 'blue')\n\n"
    "        select_option('c48', ['red', 'green', 'blue'])\n\n"
    "click(bid: str, button: Literal['left', 'middle', 'right'] = 'left', "
    "modifiers: list[typing.Literal['Alt', 'Control', 'ControlOrMeta', 'Meta', 'Shift']] = [])\n"
    "    Description: Click an element.\n"
    "    Examples:\n"
    "        click('a51')\n\n"
    "        click('b22', button='right')\n\n"
    "        click('48', button='middle', modifiers=['Shift'])\n\n"
    "dblclick(bid: str, button: Literal['left', 'middle', 'right'] = 'left', "
    "modifiers: list[typing.Literal['Alt', 'Control', 'ControlOrMeta', 'Meta', 'Shift']] = [])\n"
    "    Description: Double click an element.\n"
    "    Examples:\n"
    "        dblclick('12')\n\n"
    "        dblclick('ca42', button='right')\n\n"
    "        dblclick('178', button='middle', modifiers=['Shift'])\n\n"
    "hover(bid: str)\n"
    "    Description: Hover over an element.\n"
    "    Examples:\n"
    "        hover('b8')\n\n"
    "press(bid: str, key_comb: str)\n"
    "    Description: Focus the matching element and press a combination of keys. "
    "It accepts the logical key names that are emitted in the keyboardEvent.key property of "
    "the keyboard events: Backquote, Minus, Equal, Backslash, Backspace, Tab, Delete, Escape, "
    "ArrowDown, End, Enter, Home, Insert, PageDown, PageUp, ArrowRight, ArrowUp, F1 - F12, "
    "Digit0 - Digit9, KeyA - KeyZ, etc. You can alternatively specify a single character "
    'you\'d like to produce such as "a" or "#". Following modification shortcuts are also supported: '
    "Shift, Control, Alt, Meta, ShiftLeft, ControlOrMeta. ControlOrMeta resolves to Control on Windows "
    "and Linux and to Meta on macOS.\n"
    "    Examples:\n"
    "        press('88', 'Backspace')\n\n"
    "        press('a26', 'ControlOrMeta+a')\n\n"
    "        press('a61', 'Meta+Shift+t')\n\n"
    "focus(bid: str)\n"
    "    Description: Focus the matching element.\n"
    "    Examples:\n"
    "        focus('b455')\n\n"
    "clear(bid: str)\n"
    "    Description: Clear the input field.\n"
    "    Examples:\n"
    "        clear('996')\n\n"
    "drag_and_drop(from_bid: str, to_bid: str)\n"
    "    Description: Perform a drag & drop. Hover the element that will be dragged. "
    "Press left mouse button. Move mouse to the element that will receive the drop. Release left mouse button.\n"
    "    Examples:\n"
    "        drag_and_drop('56', '498')\n\n"
    "upload_file(bid: str, file: str | list[str])\n"
    '    Description: Click an element and wait for a "filechooser" event, '
    "then select one or multiple input files for upload. Relative file paths are resolved relative "
    "to the current working directory. An empty list clears the selected files.\n"
    "    Examples:\n"
    "        upload_file('572', '/home/user/my_receipt.pdf')\n\n"
    "        upload_file('63', ['/home/bob/Documents/image.jpg', '/home/bob/Documents/file.zip'])\n"
)
for action in _browser_action_space.action_set.values():
    assert (
        action.signature in _BROWSER_TOOL_DESCRIPTION
    ), f"Browser description mismatch. Please double check if the BrowserGym updated their action space.\n\nAction: {
        action.signature
    }"
    assert (
        action.description in _BROWSER_TOOL_DESCRIPTION
    ), f"Browser description mismatch. Please double check if the BrowserGym updated their action space.\n\nAction: {
        action.description
    }"


def create_browser_tool() -> ChatCompletionToolParam:
    """Create the browser interaction tool for the CodeAct agent."""
    return create_tool_definition(
        name=BROWSER_TOOL_NAME,
        description=_BROWSER_DESCRIPTION,
        properties={
            "code": {
                "type": "string",
                "description": "The Python code that interacts with the browser.\n"
                + _BROWSER_TOOL_DESCRIPTION,
            },
            "security_risk": get_security_risk_param(),
        },
        required=["code", "security_risk"],
    )
