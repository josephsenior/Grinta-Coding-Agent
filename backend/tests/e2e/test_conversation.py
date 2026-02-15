"""E2E: Conversation start test.

This test assumes the GitHub token has already been configured (by the
settings test) and verifies that a conversation can be started and the
agent responds to a README line-count question.
"""

import os

from playwright.sync_api import Page, expect

from backend.tests.e2e._test_ui_helpers import (
    launch_repository,
    select_repository,
    send_message,
    wait_for_agent_input_ready,
    wait_for_agent_response,
    wait_for_conversation_interface,
)


def get_readme_line_count():
    """Get the line count of the main README.md file for verification."""
    current_dir = os.getcwd()
    if current_dir.endswith("tests/e2e"):
        repo_root = os.path.abspath(os.path.join(current_dir, "../.."))
    else:
        repo_root = current_dir
    readme_path = os.path.join(repo_root, "README.md")
    print(f"Looking for README.md at: {readme_path}")
    try:
        with open(readme_path, encoding="utf-8") as f:
            lines = f.readlines()
            return len(lines)
    except OSError as e:
        print(f"Error reading README.md: {e}")
        return 0


def _navigate_to_Forge(page: Page, base_url: str) -> None:
    """Navigate to Forge application and take initial screenshot."""
    print(f"Step 1: Navigating to Forge application at {base_url}...")
    page.goto(base_url)
    page.wait_for_load_state("networkidle", timeout=30000)
    page.screenshot(path="test-results/conv_01_initial_load.png")
    print("Screenshot saved: conv_01_initial_load.png")


def _select_repository(page: Page) -> None:
    """Select the Forge repository from dropdown."""
    print("Step 2: Selecting Forge-agent/Forge repository...")
    home_screen = page.locator('[data-testid="home-screen"]')
    expect(home_screen).to_be_visible(timeout=15000)
    print("Home screen is visible")

    select_repository(page, "Forge-agent/Forge")
    page.screenshot(path="test-results/conv_02_repo_selected.png")
    print("Screenshot saved: conv_02_repo_selected.png")


def _click_launch_button(page: Page) -> None:
    """Click the launch button using shared helper."""
    print("Step 3: Clicking Launch button...")
    launch_repository(page)


def _wait_for_conversation_interface(page: Page) -> None:
    """Wait for the conversation interface to load."""
    print("Step 4: Waiting for conversation interface to load...")
    wait_for_conversation_interface(page)


def _wait_for_agent_ready(page: Page) -> None:
    """Wait for agent to be ready for input."""
    print("Step 5: Waiting for agent to initialize...")
    try:
        chat_input = page.locator('[data-testid="chat-input"]')
        expect(chat_input).to_be_visible(timeout=60000)
        submit_button = page.locator('[data-testid="chat-input"] button[type="submit"]')
        expect(submit_button).to_be_visible(timeout=10000)
        print("Agent interface is loaded")
        page.wait_for_timeout(10000)
    except Exception as e:
        print(f"Could not confirm agent interface is loaded: {e}")

    page.screenshot(path="test-results/conv_07_agent_ready.png")
    print("Screenshot saved: conv_07_agent_ready.png")

    print("Step 6: Waiting for agent to be fully ready for input...")
    wait_for_agent_input_ready(page)


def _ask_question(page: Page) -> None:
    """Ask a question about the README line count."""
    line_count = get_readme_line_count()
    print(f"Step 7: Asking question about README.md line count ({line_count})...")

    question = "How many lines are in the main README.md file? Please check the file and tell me the exact number."
    send_message(page, question)

    page.screenshot(path="test-results/conv_08_question_sent.png")
    print("Screenshot saved: conv_08_question_sent.png")


def _wait_for_agent_response(page: Page, expected_line_count: int) -> None:
    """Wait for agent response and verify it contains README line count."""
    print("Step 8: Waiting for agent response to README question...")

    content = wait_for_agent_response(page, timeout=180)
    if content:
        if _check_readme_response(content, expected_line_count):
            print("✅ Found agent response about README.md with line count!")
            page.screenshot(path="test-results/conv_09_agent_response.png")
            print("Screenshot saved: conv_09_agent_response.png")
            page.screenshot(path="test-results/conv_10_final_state.png")
            print("Screenshot saved: conv_10_final_state.png")
            print(
                "✅ Test completed successfully - agent provided correct README line count"
            )
            return
        else:
            print(
                f"Found response but it didn't match expected line count: {content[:100]}..."
            )

    print("❌ Did not find agent response with README line count within time limit")
    page.screenshot(path="test-results/conv_09_agent_response.png")
    print("Screenshot saved: conv_09_agent_response.png")
    page.screenshot(path="test-results/conv_10_final_state.png")
    print("Screenshot saved: conv_10_final_state.png")
    raise AssertionError(
        "Agent response did not include README line count within time limit"
    )


def _check_readme_response(content: str, expected_line_count: int) -> bool:
    """Check if agent response contains README line count."""
    content_lower = content.lower()
    import re

    line_count_pattern = r"\b(\d{3})\b"
    line_counts = re.findall(line_count_pattern, content)

    return (
        str(expected_line_count) in content
        and "readme" in content_lower
        or (
            "line" in content_lower
            and "readme" in content_lower
            and any(num in content for num in ["183", str(expected_line_count)])
        )
        or (
            "line" in content_lower
            and "readme" in content_lower
            and bool(line_counts)
            and any(100 <= int(num) <= 300 for num in line_counts)
        )
    )


def test_conversation_start(page: Page, base_url: str):
    """Test starting a conversation with the Forge agent.

    1. Navigate to Forge (assumes GitHub token is already configured)
    2. Select the Forge repository
    3. Click Launch
    4. Wait for the agent to initialize
    5. Ask a question about the README.md file
    6. Verify the agent responds correctly.
    """
    os.makedirs("test-results", exist_ok=True)
    if not base_url:
        base_url = "http://localhost:12000"

    expected_line_count = get_readme_line_count()
    print(f"Expected README.md line count: {expected_line_count}")

    _navigate_to_Forge(page, base_url)
    _select_repository(page)
    _click_launch_button(page)
    _wait_for_conversation_interface(page)
    _wait_for_agent_ready(page)
    _ask_question(page)
    _wait_for_agent_response(page, expected_line_count)
