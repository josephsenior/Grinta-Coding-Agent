"""Web search tool for the Orchestrator agent.

Provides a structured interface for searching the web via available
search providers. Tries (in order):

1. ``ddgr`` (DuckDuckGo CLI) — no API key required
2. ``curl`` + DuckDuckGo Lite HTML — universal fallback

The tool returns textual search-result snippets that the LLM can use
to answer questions or locate documentation.
"""

from __future__ import annotations


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
        # Fallback to scraping via HTMLParser (no fragile CSS-class regex)
        "url='https://html.duckduckgo.com/html/?q='+urllib.parse.quote(q); "
        "req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 (compatible; Forge/1.0)'}); "
        "try: "
        "    raw=urllib.request.urlopen(req, timeout=10).read().decode('utf-8','replace'); "
        "    from html.parser import HTMLParser; "
        "    class _P(HTMLParser): "
        "        def __init__(self): super().__init__(); self.results=[]; self._cur={'url':None,'title':None,'snippet':None}; self._in=''; "
        "        def handle_starttag(self,t,a): "
        "            d=dict(a); "
        "            if t=='a' and 'result__a' in d.get('class',''): self._cur['url']=d.get('href'); self._in='title'; "
        "            elif t=='a' and 'result__snippet' in d.get('class',''): self._in='snippet'; "
        "        def handle_data(self,data): "
        "            if self._in=='title': self._cur['title']=(self._cur.get('title') or '')+data; "
        "            elif self._in=='snippet': self._cur['snippet']=(self._cur.get('snippet') or '')+data; "
        "        def handle_endtag(self,t): "
        "            if t=='a': "
        "                c=self._cur; "
        "                if c.get('url') and c.get('title'): self.results.append({k:v.strip() for k,v in c.items() if v}); self._cur={'url':None,'title':None,'snippet':None}; "
        "            self._in=''; "
        "    p=_P(); p.feed(raw); rs=p.results[:n]; "
        "    print(json.dumps(rs,indent=2) if rs else '(no results found)'); "
        "except Exception as e: print(f'Search error: {e}')"
    )

    cmd = f"{sys.executable} -c \"{py_script}\""
    return CmdRunAction(command=cmd, thought=f"[WEB_SEARCH] {query}")
