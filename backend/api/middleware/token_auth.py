"""Token-based authentication middleware — auth disabled for local OSS use."""


def get_session_api_key() -> str:
    """Auth is disabled; always returns empty string."""
    return ""
