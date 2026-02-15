"""E2E: Web browsing catchphrase test (Issue #10378).

Goal: In a new conversation, instruct the agent to browse to forge.dev and
return the page's main catchphrase. We assert that a browsing action/observation
is emitted and that the agent returns the expected catchphrase.

This follows existing patterns from tests/e2e/test_conversation.py and
uses robust waits and screenshots.
"""

import os
import re
import time

from playwright.sync_api import Page, expect

from backend.tests.e2e._test_ui_helpers import (
    launch_repository,
    select_repository,
    send_message,
    wait_for_agent_response,
    wait_for_conversation_interface,
)

CATCHPHRASE_PATTERNS = ["\\bcode\\s*less\\W*make\\s*more\\b"]


def _screenshot(page: Page, name: str) -> None:
    os.makedirs("test-results", exist_ok=True)
    page.screenshot(path=f"test-results/browse_{name}.png")


def _wait_for_home_and_repo_selection(page: Page) -> None:
    home_screen = page.locator('[data-testid="home-screen"]')
    expect(home_screen).to_be_visible(timeout=30000)
    select_repository(page, "Forge-agent/Forge")


def _launch_conversation(page: Page) -> None:
    """Launch conversation using shared helper."""
    launch_repository(page)
    _screenshot(page, "after_launch_click")
    wait_for_conversation_interface(page)
    page.wait_for_timeout(5000)


def _wait_for_browsing_event(page: Page, timeout_s: int = 240) -> None:
    start = time.time()
    browse_indicators = [
        "Interactive browsing in progress",
        "Browsing the web",
        "Browsing completed",
    ]
    while time.time() - start < timeout_s:
        for text in browse_indicators:
            try:
                if page.get_by_text(text, exact=False).is_visible(timeout=2000):
                    _screenshot(page, "browsing_event_seen")
                    return
            except Exception:
                continue
        try:
            if page.get_by_text("Current URL:", exact=False).is_visible(timeout=1000):
                _screenshot(page, "browsing_url_seen")
                return
        except Exception:
            pass
        page.wait_for_timeout(2000)
    raise AssertionError("Did not observe a browsing action/observation in time")


def _wait_for_catchphrase(page: Page, timeout_s: int = 300) -> None:
    print(f"Waiting for catchphrase (up to {timeout_s}s)...")
    pattern = re.compile("|".join(CATCHPHRASE_PATTERNS), re.IGNORECASE)

    content = wait_for_agent_response(page, timeout=timeout_s)
    if content and pattern.search(content):
        _screenshot(page, "catchphrase_found")
        return

    # Check global text as fallback
    try:
        if page.get_by_text("Code Less, Make More", exact=False).is_visible(
            timeout=5000
        ):
            _screenshot(page, "catchphrase_found_global")
            return
    except Exception:
        pass

    raise AssertionError(
        "Agent did not return the expected catchphrase within time limit"
    )


def test_browsing_catchphrase(page: Page):
    os.makedirs("test-results", exist_ok=True)
    page.goto("http://localhost:12000")
    page.wait_for_load_state("networkidle", timeout=30000)
    _screenshot(page, "initial_load")
    _wait_for_home_and_repo_selection(page)
    _screenshot(page, "home_ready")
    _launch_conversation(page)
    _screenshot(page, "conversation_loaded")
    prompt = "Use the web-browsing tool to navigate to https://forge.dev and tell me the main catchphrase displayed on the page. Do not answer from memory; perform the browsing action and respond with only the exact catchphrase."
    send_message(page, prompt)
    _wait_for_browsing_event(page)
    _wait_for_catchphrase(page)
    _screenshot(page, "final_state")
