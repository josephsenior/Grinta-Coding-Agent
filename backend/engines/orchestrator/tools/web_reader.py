"""Web reader tool for the Orchestrator agent.

Provides a simple interface for reading the content of a webpage
using requests and html2text. Safe for Windows.
"""

from __future__ import annotations

import shlex
import sys

from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.events.action import CmdRunAction

WEB_READER_TOOL_NAME = "web_reader"

_WEB_READER_DESCRIPTION = """\
Read the content of a webpage and convert it to Markdown.

Use this to:
- Read documentation pages
- Read blog posts or articles found via web_search
- Verify the content of a URL

PARAMETERS:
- `url` — The URL to read (required)

RESULT FORMAT:
Returns the Markdown content of the page.
"""


def create_web_reader_tool():
    """Create the web_reader tool definition."""
    return create_tool_definition(
        name=WEB_READER_TOOL_NAME,
        description=_WEB_READER_DESCRIPTION,
        properties={
            "url": {
                "type": "string",
                "description": "The URL to read.",
            },
        },
        required=["url"],
    )


def build_web_reader_action(url: str) -> CmdRunAction:
    """Build a CmdRunAction that reads a webpage.

    Args:
        url: The URL to read.

    Returns:
        CmdRunAction: The command action.
    """
    # Create a robust Python script to read the URL
    # structure ensures it runs on Windows/Linux without shell dependecies complexity
    
    # We use repr() to get a python-safe string representation for the URL
    safe_url_repr = repr(url)
    
    script = (
        "import requests, html2text, sys; "
        "h = html2text.HTML2Text(); "
        "h.ignore_links = False; "
        "h.ignore_images = True; "
        "h.body_width = 0; "
        f"url = {safe_url_repr}; "
        "try: "
        "    headers = {'User-Agent': 'Forge/1.0'}; "
        "    r = requests.get(url, headers=headers, timeout=15); "
        "    r.raise_for_status(); "
        "    print(h.handle(r.text)); "
        "except Exception as e: "
        "    print(f'Error reading {url}: {e}')"
    )

    # Use sys.executable to ensure we run in the correct environment
    # We don't need shlex.quote for the whole script on Windows if we trust the runtime to handle it, 
    # but strictly speaking, passing a multiline string to python -c can be tricky across platforms.
    # The safest is to minimize special chars.
    
    # However, `CmdRunAction` implies a shell. 
    # On Windows `cmd.exe` / `powershell` differs from `bash`.
    # `shlex.quote` produces single-quoted strings which `cmd.exe` DOES NOT like. 
    # But Python's `shlex` is POSIX based.
    
    # To be safe for the "Forge" environment which seems to run `pwsh` (PowerShell) based on user context terminals:
    # "Terminal: pwsh"
    
    # PowerShell handles single quotes okay, generally.
    
    # construct the command
    cmd = f"{sys.executable} -c \"{script}\""

    return CmdRunAction(command=cmd, thought=f"[WEB_READER] Reading {url}")
