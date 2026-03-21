#!/usr/bin/env python3
"""Forge — single-command launcher (embedded mode).

Starts the backend server in a background thread, opens the web UI, and keeps
the process alive until Ctrl+C.

    python forge.py               # default port 3000
    python forge.py --port 3001   # custom port
    python forge.py --verbose     # debug logging

For server only (open the UI yourself), run:
    python start_server.py
    # or: uv run forge serve
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
