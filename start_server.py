#!/usr/bin/env python3
# mypy: disable-error-code=union-attr
"""Start the Forge backend server with correct Python path."""

import os
import socket
import sys
from pathlib import Path
from typing import Any

# Force UTF-8 output so emoji don't crash on Windows cp1252 terminals
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        cast_stdout: Any = sys.stdout
        cast_stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass

# Add project root to Python path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def _find_available_port(host: str, preferred_port: int, max_offset: int = 20) -> int:
    """Return preferred_port if free, otherwise next available port within range."""
    for offset in range(max_offset + 1):
        candidate = preferred_port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, candidate))
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
            if key and key not in os.environ:  # never overwrite existing env vars
                os.environ[key] = val


_load_dotenv_local()

# Set environment variables
os.environ.setdefault('PORT', '3000')

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

    reload_enabled = (
        os.environ.get('FORGE_ENV', 'development') != 'production'
        and os.environ.get('FORGE_WATCH', '1') != '0'
    )
    print(f'Starting Forge server on http://{host}:{port}')
    print('Press Ctrl+C to stop the server.\n')

    uvicorn.run(
        'backend.api.listen:app',
        host=host,
        port=port,
        log_level='info',
        reload=reload_enabled,
        reload_excludes=['./workspace'],
    )
