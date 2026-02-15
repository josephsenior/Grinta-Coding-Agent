from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page


def wait_for_conversation_interface(page: Page, timeout: int = 120) -> None:
    """Wait for the conversation interface to load.

    Args:
        page: Playwright page instance
        timeout: Maximum time to wait in seconds
    """
    start_time = time.time()
    conversation_loaded = False
    check_interval = 5000  # ms

    print(f"Waiting for conversation interface to load (up to {timeout}s)...")

    while time.time() - start_time < timeout:
        try:
            # Check for various elements that indicate the conversation is loaded
            selectors = [
                '[data-testid="chat-history"]',
                '[data-testid="chat-input"]',
                ".chat-container",
                "main",
            ]

            for selector in selectors:
                try:
                    element = page.locator(selector)
                    if element.is_visible(timeout=2000):
                        print(
                            f"Found conversation interface element with selector: {selector}"
                        )
                        conversation_loaded = True
                        break
                except Exception:
                    continue

            if conversation_loaded:
                break

            if (time.time() - start_time) % (check_interval / 1000) < 1:
                elapsed = int(time.time() - start_time)
                page.screenshot(path=f"test-results/conv_waiting_{elapsed}s.png")
                print(f"Screenshot saved: conv_waiting_{elapsed}s.png")

            page.wait_for_timeout(check_interval)
        except Exception as e:
            print(f"Error checking for conversation interface: {e}")
            page.wait_for_timeout(check_interval)

    if not conversation_loaded:
        print("Timed out waiting for conversation interface to load")
        page.screenshot(path="test-results/conv_timeout.png")
        raise TimeoutError("Timed out waiting for conversation interface to load")


def wait_for_agent_input_ready(page: Page, max_wait_time: int = 480) -> None:
    """Wait for agent to be ready for user input.

    Args:
        page: Playwright page instance
        max_wait_time: Maximum time to wait in seconds
    """
    start_time = time.time()
    agent_ready = False
    print(f"Waiting up to {max_wait_time} seconds for agent to be ready...")

    while time.time() - start_time < max_wait_time:
        elapsed = int(time.time() - start_time)
        if elapsed % 30 == 0 and elapsed > 0:
            page.screenshot(path=f"test-results/agent_waiting_{elapsed}s.png")
            print(
                f"Screenshot saved: agent_waiting_{elapsed}s.png (waiting {elapsed}s)"
            )

        try:
            status_messages = _get_status_messages(page)
            ready_indicators = [
                'div:has-text("Agent is ready")',
                'div:has-text("Waiting for user input")',
                'div:has-text("Awaiting input")',
                'div:has-text("Task completed")',
                'div:has-text("Agent has finished")',
            ]

            input_ready, submit_ready = _check_input_ready(page)
            connecting_or_starting = any(
                msg
                for msg in status_messages
                if "connecting" in msg.lower()
                or "starting" in msg.lower()
                or "runtime to start" in msg.lower()
            )
            has_ready_indicator = _check_ready_indicators(page, ready_indicators)

            if (
                (has_ready_indicator or not connecting_or_starting)
                and input_ready
                and submit_ready
            ):
                print(
                    "✅ Agent is ready for user input - input field and submit button are enabled"
                )
                agent_ready = True
                break
        except Exception as e:
            print(f"Error checking agent ready state: {e}")

        page.wait_for_timeout(2000)

    if not agent_ready:
        page.screenshot(path="test-results/agent_timeout.png")
        raise AssertionError(
            f"Agent did not become ready for input within {max_wait_time} seconds"
        )


def _get_status_messages(page: Page) -> list[str]:
    """Get status messages from the page."""
    try:
        elements = page.locator(".status-message, .agent-status").all()
        return [el.inner_text() for el in elements]
    except Exception:
        return []


def _check_input_ready(page: Page) -> tuple[bool, bool]:
    """Check if input field and submit button are ready."""
    try:
        chat_input = page.locator(
            '[data-testid="chat-input"] textarea, [data-testid="chat-input"] input'
        )
        submit_button = page.locator('[data-testid="chat-input"] button[type="submit"]')

        input_ready = chat_input.is_visible() and chat_input.is_enabled()
        submit_ready = submit_button.is_visible() and submit_button.is_enabled()

        return input_ready, submit_ready
    except Exception:
        return False, False


def _check_ready_indicators(page: Page, indicators: list[str]) -> bool:
    """Check if any ready indicators are visible."""
    for selector in indicators:
        try:
            if page.locator(selector).is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


def find_message_input(page: Page):
    """Find the message input field with fallback strategies."""
    input_selectors = [
        '[data-testid="chat-input"] textarea',
        '[data-testid="chat-input"] input',
        '[data-testid="message-input"]',
        "textarea",
        "form textarea",
        'input[type="text"]',
        '[placeholder*="message"]',
        '[placeholder*="question"]',
        '[placeholder*="ask"]',
        '[contenteditable="true"]',
    ]

    for selector in input_selectors:
        try:
            input_element = page.locator(selector)
            if input_element.is_visible(timeout=5000):
                print(f"Found message input with selector: {selector}")
                return input_element
        except Exception:
            continue

    return None


def find_submit_button(page: Page):
    """Find the submit button with fallback strategies."""
    submit_selectors = [
        '[data-testid="chat-input"] button[type="submit"]',
        'button[type="submit"]',
        'button:has-text("Send")',
        'button:has-text("Submit")',
        'button svg[data-testid="send-icon"]',
        "button.send-button",
        "form button",
        "button:right-of(textarea)",
        'button:right-of(input[type="text"])',
    ]

    for selector in submit_selectors:
        try:
            button_element = page.locator(selector)
            if button_element.is_visible(timeout=5000):
                print(f"Found submit button with selector: {selector}")
                return button_element
        except Exception:
            continue

    return None


def send_message(page: Page, message: str) -> None:
    """Send a message to the agent.

    Args:
        page: Playwright page instance
        message: Message text to send
    """
    input_field = find_message_input(page)
    if not input_field:
        page.screenshot(path="test-results/no_input_found.png")
        raise AssertionError("Could not find message input field")

    input_field.fill(message)
    print(f"Entered message: {message[:50]}...")

    submit_button = find_submit_button(page)
    if submit_button:
        # Wait for button to be enabled
        max_wait_time = 60
        start_time = time.time()
        while time.time() - start_time < max_wait_time:
            try:
                if submit_button.is_enabled():
                    break
            except Exception:
                pass
            page.wait_for_timeout(1000)

        try:
            submit_button.click()
            print("Clicked submit button")
            return
        except Exception as e:
            print(f"Click failed: {e}")

    # Fallback to Enter key
    print("Falling back to Enter key")
    input_field.press("Enter")


def wait_for_agent_response(page: Page, timeout: int = 300) -> str | None:
    """Wait for the agent to provide a response.

    Args:
        page: Playwright page instance
        timeout: Maximum time to wait in seconds

    Returns:
        The content of the latest agent message, or None if no message found
    """
    print(f"Waiting for agent response (up to {timeout}s)...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        elapsed = int(time.time() - start_time)

        try:
            agent_messages = page.locator('[data-testid="agent-message"]').all()
            if elapsed % 30 == 0 and elapsed > 0:
                print(
                    f"Found {len(agent_messages)} agent messages (waiting {elapsed}s)"
                )

            # Check if we have at least one message with content
            for msg in reversed(agent_messages):
                try:
                    content = msg.text_content()
                    if content and len(content.strip()) > 10:
                        # Found a meaningful response
                        return content
                except Exception:
                    continue

        except Exception as e:
            print(f"Error checking for agent messages: {e}")

        page.wait_for_timeout(2000)

    print("Timed out waiting for agent response")
    return None


def select_repository(page: Page, repo_name: str = "Forge-agent/Forge") -> None:
    """Select a repository from the repository dropdown.

    Args:
        page: Playwright page instance
        repo_name: Name of the repository to select
    """
    print(f"Selecting repository: {repo_name}...")

    # Find the repository selector/dropdown
    repo_selectors = [
        '[data-testid="repo-selector"]',
        '[data-testid="repository-select"]',
        ".repo-select",
        "select.repo-dropdown",
        'button:has-text("Select Repository")',
    ]

    repo_dropdown = None
    for selector in repo_selectors:
        try:
            element = page.locator(selector)
            if element.is_visible(timeout=5000):
                repo_dropdown = element
                break
        except Exception:
            continue

    if not repo_dropdown:
        print("Could not find repository dropdown, skipping selection")
        return

    repo_dropdown.click()
    page.wait_for_timeout(1000)

    try:
        # Clear existing text and type new repo name
        page.keyboard.press("Control+a")
        page.keyboard.press("Backspace")
        page.keyboard.type(repo_name)
        page.wait_for_timeout(500)
        page.keyboard.press("Enter")
        print(f"Selected repository: {repo_name}")
    except Exception as e:
        print(f"Failed to type repository name: {e}")


def launch_repository(page: Page, timeout: int = 30000) -> None:
    """Click the launch button with retry logic.

    Args:
        page: Playwright page instance
        timeout: Maximum time to wait in milliseconds
    """
    print("Clicking Launch button...")
    launch_button = page.locator('[data-testid="repo-launch-button"]')
    from playwright.sync_api import expect

    expect(launch_button).to_be_visible(timeout=10000)

    # Wait for button to be enabled
    max_wait_attempts = 30
    button_enabled = False
    for attempt in range(max_wait_attempts):
        try:
            if not launch_button.is_disabled():
                print(f"Repository Launch button is enabled (attempt {attempt + 1})")
                button_enabled = True
                break
            print(
                f"Launch button still disabled, waiting... (attempt {attempt + 1}/{max_wait_attempts})"
            )
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Error checking button state (attempt {attempt + 1}): {e}")
            page.wait_for_timeout(2000)

    try:
        if button_enabled:
            launch_button.click()
            print("Launch button clicked normally")
        else:
            print("Launch button still disabled, trying JavaScript force click...")
            page.evaluate(
                """() => {
                const button = document.querySelector('[data-testid="repo-launch-button"]');
                if (button) {
                    button.removeAttribute('disabled');
                    button.click();
                    return true;
                }
                return false;
            }"""
            )
            print("Force-clicked Launch button with JavaScript")
    except Exception as e:
        print(f"Error clicking Launch button: {e}")
        raise
