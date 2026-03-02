#!/usr/bin/env python3
"""Forge — single-command launcher (embedded mode).

Starts the backend server and TUI in one process — no second terminal needed.

    python forge.py               # default port 3000
    python forge.py --port 3001   # custom port
    python forge.py --verbose     # debug logging

For the two-terminal workflow (separate server + TUI), run:
    python start_server.py        # terminal 1
    python -m tui         # terminal 2
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.embedded import main  # noqa: E402

if __name__ == "__main__":
    main()
