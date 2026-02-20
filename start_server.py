#!/usr/bin/env python3
"""Start the Forge backend server with correct Python path."""

import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


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
    port = int(os.environ.get('PORT', '3000'))
    host = os.environ.get('FORGE_HOST', os.environ.get('HOST', '127.0.0.1'))
    reload_enabled = os.environ.get('FORGE_ENV', 'development') != 'production'
    print(f'🚀 Starting Forge server on http://{host}:{port}')
    print('Press Ctrl+C to stop the server.\n')

    uvicorn.run(
        'backend.api.listen:app',
        host=host,
        port=port,
        log_level='info',
        reload=reload_enabled,
        reload_excludes=['./workspace'],
    )
