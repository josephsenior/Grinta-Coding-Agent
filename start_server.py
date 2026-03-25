#!/usr/bin/env python3
# mypy: disable-error-code=union-attr
"""Start the Forge backend server with correct Python path."""

import os
import socket
import sys
from pathlib import Path
from typing import Any

# Force UTF-8 output so emoji don't crash on Windows cp1252 terminals
STDOUT_ENCODING = getattr(sys.stdout, "encoding", None)  # pylint: disable=invalid-name
if isinstance(STDOUT_ENCODING, str) and STDOUT_ENCODING.lower() != 'utf-8':  # pylint: disable=no-member
    try:
        cast_stdout: Any = sys.stdout
        cast_stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass

# Add project root to Python path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def _find_available_port(host_ip: str, preferred_port: int, max_offset: int = 20) -> int:
    """Return preferred_port if free, otherwise next available port within range."""
    for offset in range(max_offset + 1):
        candidate = preferred_port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host_ip, candidate))
                return candidate
            except OSError:
                continue
    return preferred_port


def _load_dotenv_local() -> None:
    """Load .env.local into os.environ if present (mirrors PS1 startup scripts)."""
    dotenv_path = project_root / ".env.local"
    if not dotenv_path.exists():
        return
    with dotenv_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if not key:
                continue

            # Only write when missing OR currently empty/whitespace.
            # This lets operators provide real values via .env.local even if
            # a hosting environment pre-defines empty placeholders.
            existing = os.environ.get(key)
            if existing is None or not str(existing).strip():
                os.environ[key] = val


_load_dotenv_local()

# Set environment variables
os.environ.setdefault('PORT', '3000')
# Prevent prolonged "Working..." when provider calls stall.
# These can still be overridden via .env.local or process environment.
os.environ.setdefault('FORGE_LLM_STEP_TIMEOUT_SECONDS', '45')
os.environ.setdefault('FORGE_LLM_FIRST_CHUNK_TIMEOUT_SECONDS', '8')

# Now import and run uvicorn
import uvicorn  # noqa: E402

if __name__ == '__main__':
    host = os.environ.get('FORGE_HOST', os.environ.get('HOST', '127.0.0.1'))
    requested_port = int(os.environ.get('PORT', '3000'))
    port = _find_available_port(host, requested_port)
    if port != requested_port:
        print(
            f'Port {requested_port} is in use; automatically switching to {port}.'
        )
        os.environ['PORT'] = str(port)

    # Reload uses a supervisor process; on Windows Ctrl+C often never reaches the worker.
    # Uvicorn owns SIGINT; keep reload off Windows entirely.
    _dev = os.environ.get('FORGE_ENV', 'development') != 'production'
    _watch = os.environ.get('FORGE_WATCH', '1').strip().lower() not in ('0', 'false', 'no', 'off')
    reload_enabled = _dev and _watch and sys.platform != 'win32'
    print(f'Starting Forge server on http://{host}:{port}')
    print('Press Ctrl+C to stop the server.\n')

    uvicorn.run(
        'backend.api.socketio_asgi_app:app',
        host=host,
        port=port,
        log_level='info',
        reload=reload_enabled,
        reload_excludes=['./workspace'],
        # Avoid websockets.legacy.server two-arg ws_handler (DeprecationWarning on websockets 15+).
        ws='websockets-sansio',
    )

