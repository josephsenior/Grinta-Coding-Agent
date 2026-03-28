"""Configuration helpers for agent skill integrations (LLM credentials etc.)."""

import os

from openai import OpenAI


def _get_openai_api_key() -> str:
    """Retrieve OpenAI API key from environment variables.

    Checks OPENAI_API_KEY first, falls back to RUNTIME_ENV_OPENAI_API_KEY,
    returns empty string if neither is set.

    Returns:
        str: OpenAI API key or empty string if not configured

    Side Effects:
        None - reads only from environment

    Notes:
        - Runtime environment supports alternative variable for testing
        - Empty string indicates misconfiguration (will cause API errors)

    """
    return os.getenv("OPENAI_API_KEY", os.getenv("RUNTIME_ENV_OPENAI_API_KEY", ""))


def _get_openai_base_url() -> str:
    """Retrieve OpenAI API base URL from environment.

    Allows override of default OpenAI endpoint for custom/proxy servers.

    Returns:
        str: API base URL, defaults to official OpenAI endpoint

    Side Effects:
        None - reads only from environment

    Notes:
        - Used for supporting alternative OpenAI-compatible servers
        - Must include protocol (https://) and version path (/v1)

    """
    return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")


def _get_openai_model() -> str:
    """Retrieve configured OpenAI model name from environment.

    Returns:
        str: Model identifier (e.g., 'gpt-4o', 'gpt-4-turbo'), defaults to 'gpt-4o'

    Side Effects:
        None - reads only from environment

    Notes:
        - Must be a valid model available through configured API endpoint
        - Affects cost and capability of LLM operations

    """
    return os.getenv("OPENAI_MODEL", "gpt-4o")


def _get_max_token() -> int:
    """Retrieve maximum token limit for LLM responses from environment.

    Returns:
        int: Maximum tokens, defaults to 500

    Side Effects:
        None - reads only from environment

    Raises:
        ValueError: If MAX_TOKEN env var is not a valid integer

    Notes:
        - Higher tokens = more expensive and slower responses
        - Must be within model's max_tokens limit

    """
    return int(os.getenv("MAX_TOKEN", "500"))


def _get_openai_client() -> OpenAI:
    """Create configured OpenAI client instance using environment settings.

    Returns:
        OpenAI: Initialized OpenAI client with configured API key and base URL

    Side Effects:
        - Calls _get_openai_api_key() and _get_openai_base_url() to read config
        - Creates new client instance on each call (no caching)

    Raises:
        If API key is empty/invalid, client initialization succeeds but API calls will fail

    Notes:
        - Client is created fresh on each call - consider caching if called frequently
        - Inherits timeout and retry behavior from OpenAI library defaults

    Example:
        >>> client = _get_openai_client()
        >>> response = client.chat.completions.create(
        ...     model=_get_openai_model(),
        ...     messages=[{"role": "user", "content": "Hi"}]
        ... )

    """
    return OpenAI(api_key=_get_openai_api_key(), base_url=_get_openai_base_url())
