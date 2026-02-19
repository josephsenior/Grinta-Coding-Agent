"""Web search tool for the CodeAct agent.

Provides a structured interface for searching the web via available
search providers. Tries (in order):

1. ``ddgr`` (DuckDuckGo CLI) — no API key required
2. ``curl`` + DuckDuckGo Lite HTML — universal fallback

The tool returns textual search-result snippets that the LLM can use
to answer questions or locate documentation.
"""

from __future__ import annotations

import shlex

from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.events.action import CmdRunAction

WEB_SEARCH_TOOL_NAME = "web_search"

_WEB_SEARCH_DESCRIPTION = """\
Search the web for information, documentation, error messages, or solutions.

Use this when you need information that is NOT in the local codebase:
- Error messages you don't recognize
- Library API documentation
- Best practices or known issues
- Version compatibility questions

PARAMETERS:
- `query` — The search query (required)
- `num_results` — Number of results to return (default: 5, max: 10)

RESULT FORMAT:
Returns a list of search results with titles, URLs, and snippets.
"""


def create_web_search_tool():
    """Create the web_search tool definition."""
    return create_tool_definition(
        name=WEB_SEARCH_TOOL_NAME,
        description=_WEB_SEARCH_DESCRIPTION,
        properties={
            "query": {
                "type": "string",
                "description": "The search query to execute.",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default: 5, max: 10).",
            },
        },
        required=["query"],
    )


def build_web_search_action(query: str, num_results: int = 5) -> CmdRunAction:
    """Build a CmdRunAction that performs a web search.

    Uses ddgr (DuckDuckGo CLI) if available, otherwise falls back
    to a curl-based DuckDuckGo Lite scrape using Python.
    Designed to be cross-platform (Windows/Linux/macOS).

    Args:
        query: Search query string.
        num_results: Number of results to return.

    Returns:
        CmdRunAction: The command action.
    """
    import sys

    num_results = max(1, min(int(num_results), 10))
    # Using repr() ensures proper escaping for the python string literal
    safe_query_repr = repr(query)

    # Python script that handles both ddgr execution (if present) and fallback scraping
    # This avoids shell-specific syntax like 'command -v' or pipes
    py_script = (
        "import shutil, subprocess, json, sys, urllib.request, urllib.parse, html, re; "
        f"q={safe_query_repr}; "
        f"n={num_results}; "
        # Try ddgr first
        "ddgr = shutil.which('ddgr'); "
        "if ddgr: "
        "    try: "
        "        # On Windows, shell=False is generally safer explicitly, but subprocess.run default is False. "
        "        # However, ddgr might be a bat file on Windows? shutil.which handles extensions. "
        "        # We use explicit execution to capture output. "
        "        res = subprocess.run([ddgr, '--json', '--num', str(n), q], capture_output=True, text=True); "
        "        if res.returncode == 0 and res.stdout.strip(): "
        "            print(res.stdout); "
        "            sys.exit(0); "
        "    except Exception: "
        "        pass; "
        # Fallback to scraping
        "url='https://lite.duckduckgo.com/lite/?q='+urllib.parse.quote(q); "
        "req=urllib.request.Request(url, headers={'User-Agent':'Forge/1.0'}); "
        "try: "
        "    resp=urllib.request.urlopen(req, timeout=10).read().decode('utf-8','replace'); "
        "    links=re.findall(r'<a[^>]+href=\"(https?://[^\"]+)\"[^>]*class=\"result-link\"[^>]*>([^<]+)</a>', resp); "
        "    snippets=re.findall(r'<td[^>]*class=\"result-snippet\"[^>]*>(.*?)</td>', resp, re.S); "
        "    results=[]; "
        "    [results.append({'url':u,'title':html.unescape(t).strip(),'snippet':html.unescape(re.sub('<[^>]+>','',s)).strip()}) for (u,t),s in zip(links[:n],snippets[:n])]; "
        "    print(json.dumps(results, indent=2) if results else '(no results found)'); "
        "except Exception as e: "
        "    print(f'Error searching: {e}')"
    )

    cmd = f"{sys.executable} -c \"{py_script}\""
    return CmdRunAction(command=cmd, thought=f"[WEB_SEARCH] {query}")
