"""Server Constants and Configuration.

This module contains global constants used throughout the server.
"""

import os

from backend.core.constants import (
    CURRENT_API_VERSION,
    ROOM_KEY_TEMPLATE,
)

# API versioning enforcement — strict by default.  Override with
# APP_PERMISSIVE_API=1 env var for unversioned routes.
ENFORCE_API_VERSIONING: bool = os.environ.get("APP_PERMISSIVE_API", "") != "1"


# API Version prefix for new endpoints
def get_api_prefix(version: str = CURRENT_API_VERSION) -> str:
    """Get the API prefix for a given version.

    Args:
        version: API version (default: current version)

    Returns:
        API prefix string (e.g., "/api/v1")

    """
    return f"/api/{version}"


# Socket.IO room key format for conversations
ROOM_KEY = ROOM_KEY_TEMPLATE
