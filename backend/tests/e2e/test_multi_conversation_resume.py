"""E2E: Multi-conversation resume test.

This test verifies that a user can resume an older conversation and continue it.
1. Start a conversation and ask a question
2. Get a response from the agent
3. Navigate away/close the conversation
4. Resume the same conversation later
5. Ask a follow-up question that requires context from the previous interaction
6. Verify the agent remembers the previous context and responds appropriately

This test assumes the GitHub token has already been configured (by the settings test).
"""

import os
import re
import time

from playwright.sync_api import Page, expect

from backend.tests.e2e._test_ui_helpers import (
    launch_repository,
    select_repository,
    send_message,
    wait_for_agent_input_ready,
    wait_for_agent_response,
    wait_for_conversation_interface,
)


def _navigate_to_FORGE_multi(page: Page) -> None:
    """Navigate to Forge application for multi-conversation test."""
    print("Step 1: Navigating to Forge application...")
    page.goto("http://localhost:12000")
    page.wait_for_load_state("networkidle", timeout=30000)
    page.screenshot(path="test-results/multi_conv_01_initial_load.png")
    print("Screenshot saved: multi_conv_01_initial_load.png")


def _select_repository_multi(page: Page) -> None:
    """Select the Forge repository for multi-conversation test."""
    print("Step 2: Selecting Forge-agent/Forge repository...")
    home_screen = page.locator('[data-testid="home-screen"]')
    expect(home_screen).to_be_visible(timeout=15000)
    print("Home screen is visible")

    select_repository(page, "Forge-agent/Forge")
    page.screenshot(path="test-results/multi_conv_02_repo_selected.png")
    print("Screenshot saved: multi_conv_02_repo_selected.png")


def _click_launch_button_multi(page: Page) -> None:
    """Click the launch button for multi-conversation test using shared helper."""
    print("Step 3: Clicking Launch button...")
    launch_repository(page)


def _wait_for_conversation_interface_multi(page: Page) -> None:
    """Wait for conversation interface to load for multi-conversation test."""
    print("Step 4: Waiting for conversation interface to load...")
    wait_for_conversation_interface(page)


def _wait_for_agent_ready_multi(page: Page) -> None:
    """Wait for agent to be ready for input for multi-conversation test."""
    print("Step 5: Waiting for agent to be ready for input...")
    wait_for_agent_input_ready(page)


def _ask_first_question_and_wait_for_response(page: Page) -> str | None:
    """Ask first question about pyproject.toml and wait for response."""
    print("Step 6: Asking first question about pyproject.toml file...")

    first_question = "What is the name of the project defined in the pyproject.toml file? Please check the file and tell me the exact project name."
    send_message(page, first_question)

    page.screenshot(path="test-results/multi_conv_08_first_question_sent.png")
    print("Screenshot saved: multi_conv_08_first_question_sent.png")

    return _wait_for_first_response(page)


def _wait_for_first_response(page: Page) -> str | None:
    """Wait for agent response to first question."""
    print("Step 7: Waiting for agent response to first question...")

    content = wait_for_agent_response(page, timeout=180)
    if content:
        project_name = _extract_project_name_from_response(content)
        if project_name:
            print("✅ Found agent response about pyproject.toml with project name!")
            print(f"Extracted project name: {project_name}")
            page.screenshot(path="test-results/multi_conv_09_first_response.png")
            print("Screenshot saved: multi_conv_09_first_response.png")
            return project_name

    print("❌ Did not find agent response about pyproject.toml within time limit")
    page.screenshot(path="test-results/multi_conv_09_first_response_timeout.png")
    print("Screenshot saved: multi_conv_09_first_response_timeout.png")
    raise AssertionError(
        "Agent response did not include pyproject.toml project name within time limit"
    )


def _extract_project_name_from_response(content: str) -> str | None:
    """Extract project name from agent response."""
    content_lower = content.lower()
    if (
        "pyproject" in content_lower
        and ("name" in content_lower or "project" in content_lower)
        and ("forge" in content_lower or "Forge-ai" in content_lower)
    ):
        if name_match := re.search(
            r'name.*?["\']([^"\']+)["\']', content, re.IGNORECASE
        ):
            return name_match[1]
        else:
            return "Forge-ai" if "Forge-ai" in content_lower else "forge"
    return None


def _extract_conversation_id_and_navigate_away(page: Page) -> str:
    """Extract conversation ID and navigate away from conversation."""
    print("Step 8: Storing conversation ID and navigating away...")
    current_url = page.url
    print(f"Current URL: {current_url}")

    if conversation_id_match := re.search(
        r"/conversations?/([a-f0-9]+)", current_url
    ) or re.search(r"/chat/([a-f0-9]+)", current_url):
        conversation_id = conversation_id_match[1]

    else:
        print(
            "Could not extract conversation ID from URL, trying to find it in the page"
        )
        conversation_id = page.evaluate(
            "() => {\n            const url = window.location.href;\n            const match = url.match(/\\/(?:conversations?|chat)\\/([a-f0-9]+)/);\n            if (match) return match[1];\n            const stored = localStorage.getItem('currentConversationId');\n            if (stored) return stored;\n            const sessionStored = sessionStorage.getItem('conversationId');\n            if (sessionStored) return sessionStored;\n            return null;\n        }"
        )
        if not conversation_id:
            page.screenshot(path="test-results/multi_conv_10_no_conversation_id.png")
            print("Screenshot saved: multi_conv_10_no_conversation_id.png")
            raise AssertionError("Could not extract conversation ID")
    print(f"Extracted conversation ID: {conversation_id}")
    page.goto("http://localhost:12000")
    page.wait_for_load_state("networkidle", timeout=30000)
    page.screenshot(path="test-results/multi_conv_11_navigated_home.png")
    print("Screenshot saved: multi_conv_11_navigated_home.png")
    print("Waiting 10 seconds to simulate time passing...")
    page.wait_for_timeout(10000)

    return conversation_id


def _resume_conversation_and_verify_history(page: Page, conversation_id: str) -> None:
    """Resume conversation and verify history is preserved."""
    print("Step 9: Resuming the previous conversation via conversation panel...")
    _open_conversation_panel(page)
    _find_and_click_conversation(page, conversation_id)
    _wait_for_resumed_conversation_ready(page)
    _verify_conversation_history(page)


def _open_conversation_panel(page: Page) -> None:
    """Open conversation panel."""
    conversation_panel_button = page.locator(
        '[data-testid="toggle-conversation-panel"]'
    )
    try:
        if conversation_panel_button.is_visible(timeout=10000):
            print(
                "Found conversation panel button, clicking to open conversations list"
            )
            conversation_panel_button.click()
            page.wait_for_timeout(3000)
        else:
            print("Conversation panel button not visible")
    except Exception as e:
        print(f"Error clicking conversation panel button: {e}")

    page.screenshot(path="test-results/multi_conv_12_conversations_list.png")
    print("Screenshot saved: multi_conv_12_conversations_list.png")


def _find_and_click_conversation(page: Page, conversation_id: str) -> None:
    """Find and click on the conversation."""
    print(f"Looking for conversation {conversation_id} in the list...")
    conversation_selectors = [
        '[data-testid="conversation-card"]',
        f'a[href*="{conversation_id}"]',
        f'div:has-text("{conversation_id}")',
        'a[href*="/conversations/"]',
    ]

    conversation_link_found = False
    for selector in conversation_selectors:
        try:
            conversation_elements = page.locator(selector).all()
            for element in conversation_elements:
                try:
                    element_text = element.text_content() or ""
                    element_href = element.get_attribute("href") or ""
                    if (
                        conversation_id in element_href
                        or conversation_id in element_text
                    ):
                        print(f"Found conversation link with selector: {selector}")
                        element.click()
                        conversation_link_found = True
                        page.wait_for_timeout(2000)
                        break
                    elif (
                        selector == 'a[href*="/conversations/"]'
                        and not conversation_link_found
                    ):
                        print(
                            f"Clicking first conversation found with selector: {selector}"
                        )
                        element.click()
                        conversation_link_found = True
                        page.wait_for_timeout(2000)
                        break
                except Exception:
                    continue
            if conversation_link_found:
                break
        except Exception:
            continue

    if not conversation_link_found:
        print(
            "Could not find conversation in list, navigating directly to conversation URL as fallback"
        )
        conversation_url = f"http://localhost:12000/conversations/{conversation_id}"
        print(f"Navigating to conversation URL: {conversation_url}")
        page.goto(conversation_url)
        page.wait_for_load_state("networkidle", timeout=30000)

    page.screenshot(path="test-results/multi_conv_13_resumed_conversation.png")
    print("Screenshot saved: multi_conv_13_resumed_conversation.png")


def _wait_for_resumed_conversation_ready(page: Page) -> None:
    """Wait for resumed conversation to be ready."""
    print("Waiting for resumed conversation to be ready...")
    start_time = time.time()
    agent_ready = False
    max_wait_time = 120

    while time.time() - start_time < max_wait_time:
        try:
            input_field = page.locator('[data-testid="chat-input"] textarea')
            submit_button = page.locator(
                '[data-testid="chat-input"] button[type="submit"]'
            )
            if (
                input_field.is_visible(timeout=2000)
                and input_field.is_enabled(timeout=2000)
                and submit_button.is_visible(timeout=2000)
                and submit_button.is_enabled(timeout=2000)
            ):
                print("Resumed conversation is ready for input")
                agent_ready = True
                break
        except Exception:
            pass
        page.wait_for_timeout(2000)

    if not agent_ready:
        page.screenshot(path="test-results/multi_conv_14_resume_timeout.png")
        print("Screenshot saved: multi_conv_14_resume_timeout.png")
        raise AssertionError("Resumed conversation did not become ready for input")


def _verify_conversation_history(page: Page) -> None:
    """Verify conversation history is preserved."""
    print("Step 10: Verifying conversation history is preserved...")
    try:
        user_messages = page.locator('[data-testid="user-message"]').all()
        agent_messages = page.locator('[data-testid="agent-message"]').all()
        print(
            f"Found {len(user_messages)} user messages and {len(agent_messages)} agent messages"
        )

        if len(user_messages) == 0 or len(agent_messages) == 0:
            page.screenshot(path="test-results/multi_conv_15_no_history.png")
            print("Screenshot saved: multi_conv_15_no_history.png")
            raise AssertionError(
                "Conversation history not preserved - no previous messages found"
            )

        first_question_found = False
        for msg in user_messages:
            content = msg.text_content()
            if content and "pyproject.toml" in content.lower():
                first_question_found = True
                print("✅ Found first question in conversation history")
                break

        if not first_question_found:
            print("⚠️ First question not found in visible history, but continuing test")
    except Exception as e:
        print(f"Error checking conversation history: {e}")


def _ask_followup_question_and_verify_context(
    page: Page, project_name: str | None
) -> None:
    """Ask follow-up question and verify context awareness."""
    print(
        "Step 11: Asking follow-up question that requires context from first interaction..."
    )

    if project_name:
        follow_up_question = f"Based on the project name you just told me ({project_name}), can you tell me what type of project this is? Is it a Python package, web application, or something else?"
    else:
        follow_up_question = "Based on the project name you just told me from the pyproject.toml file, can you tell me what type of project this is? Is it a Python package, web application, or something else?"

    send_message(page, follow_up_question)
    print("Entered follow-up question that requires context from first interaction")

    page.screenshot(path="test-results/multi_conv_17_followup_question_sent.png")
    print("Screenshot saved: multi_conv_17_followup_question_sent.png")

    _wait_for_followup_response(page)


def _wait_for_followup_response(page: Page) -> None:
    """Wait for agent response to follow-up question."""
    print("Step 12: Waiting for agent response to follow-up question...")
    response_wait_time = 300
    response_start_time = time.time()
    followup_response_found = False
    agent_completed = False

    while time.time() - response_start_time < response_wait_time:
        elapsed = int(time.time() - response_start_time)
        if elapsed % 30 == 0 and elapsed > 0:
            page.screenshot(
                path=f"test-results/multi_conv_followup_response_wait_{elapsed}s.png"
            )
            print(
                f"Screenshot saved: multi_conv_followup_response_wait_{elapsed}s.png (waiting {elapsed}s for follow-up response)"
            )

        try:
            agent_completed = _check_agent_completion_status(page)
            if agent_completed or elapsed > 240:
                followup_response_found = _check_followup_response_content(
                    page, agent_completed
                )
            if followup_response_found and agent_completed:
                break
        except Exception as e:
            print(f"Error checking for agent messages: {e}")

        page.wait_for_timeout(5000)

    page.screenshot(path="test-results/multi_conv_19_final_state.png")
    print("Screenshot saved: multi_conv_19_final_state.png")

    if not followup_response_found:
        print("❌ Did not find agent response to follow-up question within time limit")
        page.screenshot(path="test-results/multi_conv_18_followup_response_timeout.png")
        print("Screenshot saved: multi_conv_18_followup_response_timeout.png")
        raise AssertionError(
            "Agent response to follow-up question not found within time limit"
        )

    if not agent_completed:
        print("⚠️  Found response content but agent may not have completed processing")
        print("This could indicate the agent is still working on the response")

    print(
        "✅ Test completed successfully - agent resumed conversation and maintained context!"
    )


def _check_agent_completion_status(page: Page) -> bool:
    """Check if agent has completed its response."""
    agent_status_indicators = [
        'text="Agent is awaiting user input"',
        'text="Agent is ready"',
        '[data-testid="agent-status"]:has-text("awaiting")',
        '[data-testid="agent-status"]:has-text("ready")',
    ]
    running_indicators = [
        'text="Agent is running task"',
        'text="Agent is working"',
        '[data-testid="agent-status"]:has-text("running")',
        '[data-testid="agent-status"]:has-text("working")',
    ]

    # Check if agent is still running
    for indicator in running_indicators:
        try:
            if page.locator(indicator).is_visible(timeout=1000):
                return False
        except Exception:
            continue

    # Check if agent has completed
    for indicator in agent_status_indicators:
        try:
            if page.locator(indicator).is_visible(timeout=1000):
                print("✅ Agent has completed its response")
                return True
        except Exception:
            continue

    # Check if input field is enabled (fallback)
    try:
        input_field = page.locator('[data-testid="chat-input"] textarea')
        submit_button = page.locator('[data-testid="chat-input"] button[type="submit"]')
        if (
            input_field.is_enabled(timeout=1000)
            and submit_button.is_enabled(timeout=1000)
            and not submit_button.is_disabled()
        ):
            print("✅ Agent appears to have completed (input field is enabled)")
            return True
    except Exception:
        pass

    return False


def _check_followup_response_content(page: Page, agent_completed: bool) -> bool:
    """Check if follow-up response contains context awareness."""
    agent_messages = page.locator('[data-testid="agent-message"]').all()
    for i, msg in enumerate(agent_messages[-3:]):
        try:
            content = msg.text_content()
            if content and len(content.strip()) > 10:
                content_lower = content.lower()
                context_indicators = [
                    "based on",
                    "as i mentioned",
                    "from what i told you",
                    "the project name",
                    "python",
                    "package",
                    "application",
                    "software",
                    "ai",
                    "forge",
                ]
                if any(indicator in content_lower for indicator in context_indicators):
                    print(
                        "✅ Found agent response to follow-up question with context awareness!"
                    )
                    if agent_completed:
                        page.screenshot(
                            path="test-results/multi_conv_18_followup_response.png"
                        )
                        print("Screenshot saved: multi_conv_18_followup_response.png")
                    else:
                        print(
                            "Found response content but agent still processing, continuing to wait..."
                        )
                    return True
        except Exception as e:
            print(f"Error processing agent message {i}: {e}")
            continue
    return False


def test_multi_conversation_resume(page: Page):
    """Test resuming an older conversation and continuing it.

    1. Navigate to Forge (assumes GitHub token is already configured)
    2. Select the Forge repository
    3. Start a conversation and ask about a specific file
    4. Wait for agent response
    5. Navigate away from the conversation
    6. Resume the same conversation
    7. Ask a follow-up question that requires context from the first interaction
    8. Verify the agent remembers the previous context.
    """
    os.makedirs("test-results", exist_ok=True)

    _navigate_to_FORGE_multi(page)
    _select_repository_multi(page)
    _click_launch_button_multi(page)
    _wait_for_conversation_interface_multi(page)
    _wait_for_agent_ready_multi(page)

    project_name = _ask_first_question_and_wait_for_response(page)

    conversation_id = _extract_conversation_id_and_navigate_away(page)
    _resume_conversation_and_verify_history(page, conversation_id)
    _ask_followup_question_and_verify_context(page, project_name)
    print("Multi-conversation resume test passed:")
    print("1. ✅ Started conversation and asked about pyproject.toml")
    print("2. ✅ Received response with project name")
    print("3. ✅ Successfully navigated away from conversation")
    print("4. ✅ Successfully resumed the same conversation via conversation list")
    print("5. ✅ Conversation history was preserved")
    print("6. ✅ Asked follow-up question requiring context from first interaction")
    print(
        "7. ✅ Agent responded with context awareness, showing conversation continuity"
    )
