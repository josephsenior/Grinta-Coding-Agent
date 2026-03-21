"""Pattern checkers for error message classification.

Used by error_formatter to match generic exceptions to specific formatters
based on message content.
"""


def check_rate_limit_pattern(error_message: str) -> bool:
    """Check if error message indicates rate limiting."""
    return "rate limit" in error_message or "too many requests" in error_message


def check_auth_pattern(error_message: str) -> bool:
    """Check if error message indicates authentication failure."""
    return any(
        keyword in error_message
        for keyword in [
            "authentication",
            "unauthorized",
            "invalid token",
            "api key",
            "check your api key",
            "authentication with the llm provider",
        ]
    )


def check_network_pattern(error_message: str) -> bool:
    """Check if error message indicates network error."""
    return any(
        keyword in error_message for keyword in ["connection", "timeout", "network"]
    )


def check_file_not_found_pattern(error_message: str) -> bool:
    """Check if error message indicates file not found."""
    return "file not found" in error_message or "no such file" in error_message


def check_permission_pattern(error_message: str) -> bool:
    """Check if error message indicates permission error."""
    return "permission denied" in error_message or "forbidden" in error_message
