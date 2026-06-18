"""Textual CSS for ActivityCard."""

ACTIVITY_CARD_DEFAULT_CSS = """
    ActivityCard {
        width: 100%;
        height: auto;
        margin: 0;
        border: round #1b233a;
        background: #08101d;
        padding: 0 0 0 1;
    }
    ActivityCard:focus {
        border: round #4a5f99;
        background: #0d162a;
    }
    ActivityCard:hover {
        background: #0a1323;
        border: round #26365b;
    }
    ActivityCard.-category-shell,
    ActivityCard.-category-terminal,
    ActivityCard.-category-debugger {
        border: round #24385c;
        background: #050913;
    }
    ActivityCard.-category-shell.-running,
    ActivityCard.-category-terminal.-running,
    ActivityCard.-category-debugger.-running {
        border-left: heavy #5eead4;
    }
    ActivityCard.-expanded.-category-shell,
    ActivityCard.-expanded.-category-terminal,
    ActivityCard.-expanded.-category-debugger {
        border: round #24385c;
        padding: 0;
    }
    ActivityCard.-collapsed.-category-shell .card-collapsed-text,
    ActivityCard.-collapsed.-category-terminal .card-collapsed-text,
    ActivityCard.-collapsed.-category-debugger .card-collapsed-text {
        color: #cbd5e1;
    }
    ActivityCard.-category-grep,
    ActivityCard.-category-glob,
    ActivityCard.-category-search,
    ActivityCard.-category-find_symbols,
    ActivityCard.-category-read_symbols,
    ActivityCard.-category-analyze {
        border: round #2d4a6a;
        background: #050c14;
    }
    ActivityCard.-category-web_search,
    ActivityCard.-category-web_fetch {
        border: round #3a4a6a;
        background: #060d18;
    }
    ActivityCard.-category-browser {
        border: round #3d5a4a;
        background: #060f0c;
    }
    ActivityCard.-category-mcp {
        border: round #3a3d5a;
        background: #080a14;
    }
    ActivityCard.-collapsed {
        border: none;
        border-left: solid #1b233a;
        padding: 0 1 0 1;
    }
    ActivityCard.-collapsed:focus {
        border-left: solid #4a5f99;
    }
    ActivityCard.-collapsed:hover {
        border-left: solid #26365b;
    }
    ActivityCard.-collapsed.-category-shell,
    ActivityCard.-collapsed.-category-terminal,
    ActivityCard.-collapsed.-category-debugger {
        border-left: solid #24385c;
    }
    ActivityCard.-collapsed.-category-grep,
    ActivityCard.-collapsed.-category-glob,
    ActivityCard.-collapsed.-category-search,
    ActivityCard.-collapsed.-category-find_symbols,
    ActivityCard.-collapsed.-category-read_symbols,
    ActivityCard.-collapsed.-category-analyze {
        border-left: solid #2d4a6a;
    }
    ActivityCard.-collapsed.-category-web_search,
    ActivityCard.-collapsed.-category-web_fetch {
        border-left: solid #3a4a6a;
    }
    ActivityCard.-collapsed.-category-browser {
        border-left: solid #3d5a4a;
    }
    ActivityCard.-collapsed.-category-mcp {
        border-left: solid #3a3d5a;
    }
    ActivityCard #collapsed-row-container {
        width: 100%;
        height: 1;
        layout: horizontal;
    }
    ActivityCard .card-collapsed-text {
        width: 1fr;
        height: 1;
    }
    ActivityCard.-pinned {
        border-left: heavy #f6ff8f;
    }
    ActivityCard.-collapsed.-pinned {
        border-left: heavy #f6ff8f;
    }
    ActivityCard .card-pin {
        width: 2;
        height: 1;
        content-align: center middle;
        color: #f6ff8f;
    }
    ActivityCard .card-pin.-hidden {
        display: none;
    }
    ActivityCard .card-caret {
        width: 3;
        height: 1;
        content-align: right middle;
        color: #54597b;
        padding: 0 1 0 0;
    }
    ActivityCard .card-caret:hover {
        color: #91abec;
    }
    ActivityCard .card-expanded-body {
        width: 100%;
        height: auto;
        padding: 0 1;
        margin: 1 0;
    }
    ActivityCard .card-extra-content {
        width: 100%;
        height: auto;
    }
    ActivityCard .card-meta-row {
        width: 100%;
        height: auto;
        padding: 0 1;
        color: #54597b;
    }
    ActivityCard .card-meta-row.-hidden {
        display: none;
    }
    """
