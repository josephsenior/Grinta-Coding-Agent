"""Helper functions for checking server readiness before browser navigation.

This helps prevent navigation to chrome-error://chromewebdata/ by ensuring
the server is ready before attempting to browse to it.
"""

import time

import requests

from backend.core.logger import forge_logger as logger


def wait_for_server_ready(
    url: str,
    max_wait_time: int = 30,
    check_interval: float = 1.0,
    timeout: int = 5,
) -> bool:
    """Wait for a server to be ready by checking if it responds to HTTP requests.

    Args:
        url: The URL to check (e.g., "http://localhost:8000")
        max_wait_time: Maximum time to wait in seconds (default: 30)
        check_interval: Time between checks in seconds (default: 1.0)
        timeout: HTTP request timeout in seconds (default: 5)

    Returns:
        True if server is ready, False if timeout exceeded

    """
    logger.info("Waiting for server at %s to be ready (max %ss)...", url, max_wait_time)

    start_time = time.time()
    while time.time() - start_time < max_wait_time:
        try:
            # Try to make a simple HEAD request to check if server is responding
            response = requests.head(url, timeout=timeout, allow_redirects=True)
            if response.status_code < 500:  # Accept any non-server-error response
                logger.info(
                    "Server at %s is ready (status: %s)", url, response.status_code
                )
                return True
        except requests.exceptions.RequestException as e:
            logger.debug("Server at %s not ready yet: %s", url, e)

        time.sleep(check_interval)

    logger.warning(
        "Server at %s did not become ready within %s seconds", url, max_wait_time
    )
    return False


def check_server_ready(url: str, timeout: int = 5) -> bool:
    """Check if a server is currently ready without waiting.

    Args:
        url: The URL to check
        timeout: HTTP request timeout in seconds

    Returns:
        True if server is ready, False otherwise

    """
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        return response.status_code < 500
    except requests.exceptions.RequestException:
        return False


def safe_goto_localhost(
    url: str, max_wait: int = 30, check_interval: float = 1.0
) -> str:
    """Safely navigate to a localhost URL by waiting for server readiness.

    Args:
        url: The localhost URL to navigate to
        max_wait: Maximum time to wait for server readiness (seconds)
        check_interval: Time between readiness checks (seconds)

    Returns:
        Browser code that safely navigates to the URL

    """
    if not url.startswith(
        (
            "http://localhost:",
            "https://localhost:",
            "http://127.0.0.1:",
            "https://127.0.0.1:",
        )
    ):
        return f"goto('{url}')"

    logger.info("Creating safe navigation code for %s", url)

    # Generate the safe navigation code using the helper
    return safe_navigate_to_url(
        f"goto('{url}')\nnoop(2000)", url, max_wait, check_interval
    )


def safe_navigate_to_url(
    browser_code: str,
    url: str,
    max_wait_time: int = 30,
    check_interval: float = 1.0,
) -> str:
    """Generate browser code that safely navigates to a URL after ensuring server readiness.

    Args:
        browser_code: The existing browser code
        url: The URL to navigate to
        max_wait_time: Maximum time to wait for server readiness
        check_interval: Time between readiness checks

    Returns:
        Updated browser code with server readiness check

    """
    if not url.startswith(("http://", "https://")):
        logger.warning("URL %s doesn't appear to be a valid HTTP URL", url)
        return browser_code

    return f"""
# Wait for server to be ready before navigating
import time
import requests

def wait_for_server_ready():
    \"\"\"Wait for a server to become ready before proceeding.

    This function checks if a server is responding to requests within
    the specified timeout period and check interval.

    Returns:
        bool: True if the server becomes ready, False if timeout is reached.
    \"\"\"
    url = "{url}"
    max_wait = {max_wait_time}
    check_interval = {check_interval}

    print(f"🔍 Checking if server at {{url}} is ready...")
    start_time = time.time()

    while time.time() - start_time < max_wait:
        try:
            # Try to make a simple HEAD request to check if server is responding
            response = requests.head(url, timeout=5, allow_redirects=True)
            if response.status_code < 500:  # Accept any non-server-error response
                print(f"✅ Server is ready! Status: {{response.status_code}}")
                return True
        except Exception as e:
            # Server not ready yet
            pass

        time.sleep(check_interval)

    print(f"⚠️ Server did not become ready within {{max_wait}} seconds")
    return False

# Check server readiness
if wait_for_server_ready():
    print("Navigating to the webpage...")
else:
    print("⚠️ Proceeding with navigation despite server not being ready")

# Original browser code
{browser_code}
"""


def create_safe_navigation_browser_code(url: str, additional_actions: str = "") -> str:
    """Create browser code that safely navigates to a URL with server readiness check.

    Args:
        url: The URL to navigate to
        additional_actions: Additional browser actions to perform after navigation

    Returns:
        Complete browser code with safety checks

    """
    base_code = f"""
# Navigate to the created webpage
goto("{url}")
"""

    if additional_actions:
        base_code += f"\n{additional_actions}"

    return safe_navigate_to_url(base_code, url)
