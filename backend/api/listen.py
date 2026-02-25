"""Socket.IO entrypoint that mounts the FastAPI app."""

import socketio  # type: ignore[import-untyped]

from backend.core.logger import forge_logger as logger
from backend.api.app import app as base_app
from backend.api.shared import sio

# Import Socket.IO handlers to register them - this MUST be after sio is imported
try:
    from backend.api import listen_socket  # noqa: F401
except Exception as e:
    logger.error("Failed to import Socket.IO handlers: %s", e, exc_info=True)
else:
    logger.debug("Socket.IO handlers registered successfully")


# Note: Middleware is already added in app.py (LocalhostCORSMiddleware, TokenAuth)
# Do NOT duplicate middleware here to avoid double rate-limiting and duplicate CORS headers

app = socketio.ASGIApp(sio, other_asgi_app=base_app)
