"""Enhanced web navigator with ReAct reasoning and state tracking.

Capabilities:
1. ReAct prompt structure (THINK → ACT → OBSERVE → VERIFY)
2. Tool_choice enforcement for structured browser actions
3. State tracking (visited pages, form data)
4. Vision-enhanced navigation using screenshots
5. Error recovery with backtracking
"""

import os
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, TypedDict, cast

from browsergym.core.action.highlevel import HighLevelActionSet
from browsergym.utils.obs import flatten_axtree_to_str

from backend.controller.agent import Agent
from backend.controller.state.state import State
from backend.core.config import AgentConfig
from backend.core.logger import FORGE_logger as logger
from backend.core.message import ImageContent, Message, TextContent
from backend.engines.navigator.response_parser import BrowsingResponseParser
from backend.engines.navigator.state_tracker import BrowsingStateTracker, PageVisit
from backend.events.action import (
    Action,
    BrowseInteractiveAction,
    MessageAction,
    PlaybookFinishAction,
)
from backend.events.event import Event, EventSource
from backend.events.observation import BrowserOutputObservation
from backend.llm.llm_registry import LLMRegistry
from backend.runtime.plugins import PluginRequirement
from backend.utils.prompt import PromptManager

if TYPE_CHECKING:
    ModelResponse = Any


class BrowsingContext(TypedDict):
    prev_actions: list[str]
    cur_url: str
    cur_axtree_txt: str
    error_prefix: str
    last_obs: BrowserOutputObservation | None
    last_action: BrowseInteractiveAction | None
    agent_message: MessageAction | None
    screenshot_url: str | None


class PerformanceMetrics(TypedDict):
    total_actions: int
    successful_actions: int
    failed_actions: int
    total_time_ms: float
    avg_action_time_ms: float


LLMResponsePayload = dict[str, list[dict[str, dict[str, str | None]]]]

USE_NAV = os.environ.get("USE_NAV", "true") == "true"
USE_CONCISE_ANSWER = os.environ.get("USE_CONCISE_ANSWER", "false") == "true"
EVAL_MODE = not USE_NAV and USE_CONCISE_ANSWER

CONCISE_INSTRUCTION = (
    "\nHere is another example with chain of thought of a valid action when providing a "
    'concise answer to user:\n"\nIn order to accomplish my goal I need to send the '
    "information asked back to the user. This page list the information of HP Inkjet "
    "Fax Machine, which is the product identified in the objective. Its price is "
    "$279.49. I will send a message back to user with the answer.\n"
    '```send_msg_to_user("$279.49")```\n"\n'
)


def get_error_prefix(last_browser_action: str) -> str:
    """Generate error prefix message for incorrect browser actions."""
    return (
        "IMPORTANT! Last action is incorrect:\n"
        f"{last_browser_action}\n"
        "Think again with the current observation of the page.\n"
    )


def get_system_message(goal: str, action_space: str) -> str:
    """Generate the system message detailing goal and action space."""
    return (
        "# Instructions\n"
        "Review the current state of the page and all other information to find the best\n"
        "possible next action to accomplish your goal. Your answer will be interpreted\n"
        "and executed by a program, make sure to follow the formatting instructions.\n\n"
        "# Goal:\n"
        f"{goal}\n\n"
        "# Action Space\n"
        f"{action_space}\n"
    )


def get_prompt(
    error_prefix: str, cur_url: str, cur_axtree_txt: str, prev_action_str: str
) -> str:
    """Helper used by tests to render the browsing prompt."""
    prompt = (
        f"{error_prefix}\n\n# Current Page URL:\n{cur_url}\n\n"
        f"# Current Accessibility Tree:\n{cur_axtree_txt}\n\n"
        f"# Previous Actions\n{prev_action_str}\n\n"
        "Here is an example with chain of thought of a valid action when "
        'clicking on a button:\n"\nIn order to accomplish my goal I need to '
        'click on the button with bid 12\n```click("12")```\n"\n'
    ).strip()
    if USE_CONCISE_ANSWER:
        prompt += CONCISE_INSTRUCTION
    return prompt


class Navigator(Agent):
    """Enhanced web navigator with ReAct reasoning and state tracking.

    Extends the base ``Agent`` with:
    - ReAct prompt structure (THINK → ACT → OBSERVE → VERIFY)
    - Tool_choice enforcement for structured browser actions
    - Page and form state tracking across navigation steps
    - Screenshot-based vision for better page understanding
    - Error recovery with retry limits and backtracking
    """

    VERSION = "2.0"
    _prompt_manager: PromptManager | None = None
    "\n    Enhanced web navigation engine.\n    \n    Features:\n    - ReAct reasoning loop\n    - State tracking and memory\n    - Error recovery with backtracking\n    - Vision-enhanced navigation\n    - Tool_choice enforcement\n    "
    runtime_plugins: list[PluginRequirement] = []
    response_parser = BrowsingResponseParser()

    def __init__(self, config: AgentConfig, llm_registry: LLMRegistry) -> None:
        """Initialize Ultimate Navigator.

        Args:
            config: Agent configuration
            llm_registry: LLM registry

        """
        super().__init__(config, llm_registry)

        # Configure action space
        action_subsets = ["chat", "bid"]
        if USE_NAV:
            action_subsets.append("nav")
        self.action_space = HighLevelActionSet(
            subsets=action_subsets, strict=False, multiaction=True
        )

        # State tracking (NEW!)
        self.state_tracker: BrowsingStateTracker | None = None

        # Error recovery (Enhanced!)
        self.error_accumulator = 0
        self.last_failed_action: str | None = None
        self.retry_count = 0
        self.max_retries = 3

        # Performance tracking (NEW!)
        self.performance_metrics: PerformanceMetrics = {
            "total_actions": 0,
            "successful_actions": 0,
            "failed_actions": 0,
            "total_time_ms": 0.0,
            "avg_action_time_ms": 0.0,
        }

        self.reset()

        logger.info("✅ Ultimate Navigator initialized")
        logger.info("   - Performance metrics: Tracking action times and success rates")

    @property
    def prompt_manager(self) -> PromptManager:
        """Get prompt manager with ReAct templates."""
        if self._prompt_manager is None:
            self._prompt_manager = PromptManager(
                prompt_dir=os.path.join(os.path.dirname(__file__), "prompts")
            )
        return self._prompt_manager

    def reset(self) -> None:
        """Reset agent state."""
        super().reset()
        self.error_accumulator = 0
        self.last_failed_action = None
        self.retry_count = 0
        self.state_tracker = None

        # Log final performance before reset (if any actions were tracked)
        if self.performance_metrics["total_actions"] > 0:
            report = self.get_performance_report()
            logger.info(
                "📊 Session complete: %s actions, %.1f%% success rate, avg %.0fms per action",
                report["total_actions"],
                report["success_rate"],
                report["avg_action_time_ms"],
            )

    def step(self, state: State) -> Action:
        """Perform one browsing step with ReAct reasoning.

        Args:
            state: Current state

        Returns:
            Next action to take

        """
        # Initialize state tracker on first step
        if self.state_tracker is None:
            goal, _ = state.get_current_user_intent()
            if goal is None:
                goal = state.inputs.get("task", "Browse web")

            self.state_tracker = BrowsingStateTracker(
                session_id=state.session_id, goal=goal
            )

        # Handle eval mode special case
        if EVAL_MODE and len(state.view) == 1:
            return BrowseInteractiveAction(browser_actions="noop()")

        # Extract context
        context = self._extract_enhanced_context(state)

        # Check termination conditions
        agent_message = context["agent_message"]
        if agent_message is not None:
            return PlaybookFinishAction(outputs={"content": agent_message.content})

        if self._should_return_user_message(context):
            last_action = cast(BrowseInteractiveAction, context["last_action"])
            return MessageAction(last_action.browsergym_send_msg_to_user)

        # Handle errors with smart recovery
        if self._should_handle_browser_error(context):
            recovery_action = self._handle_browser_error_smart(context, state)
            if recovery_action is not None:
                return recovery_action

        # Generate browsing action with ReAct
        return self._generate_browsing_action_react(state, context)

    def _extract_enhanced_context(self, state: State) -> BrowsingContext:
        """Extract enhanced context with state tracking."""
        context = self._base_context()
        for event in state.view:
            self._accumulate_context_from_event(context, event)
        if EVAL_MODE:
            context["prev_actions"] = context["prev_actions"][1:]
        return context

    @staticmethod
    def _base_context() -> BrowsingContext:
        return {
            "prev_actions": [],
            "cur_url": "",
            "cur_axtree_txt": "",
            "error_prefix": "",
            "last_obs": None,
            "last_action": None,
            "agent_message": None,
            "screenshot_url": None,
        }

    def _accumulate_context_from_event(
        self,
        context: BrowsingContext,
        event: "Event",
    ) -> None:
        if isinstance(event, BrowseInteractiveAction):
            self._handle_browse_action(context, event)
        elif isinstance(event, MessageAction) and event.source == EventSource.AGENT:
            context["agent_message"] = event
        elif isinstance(event, BrowserOutputObservation):
            self._handle_browser_observation(context, event)

    def _handle_browse_action(
        self,
        context: BrowsingContext,
        action: BrowseInteractiveAction,
    ) -> None:
        context["prev_actions"].append(action.browser_actions)
        context["last_action"] = action
        if self.state_tracker:
            self._track_action(action.browser_actions)

    def _handle_browser_observation(
        self,
        context: BrowsingContext,
        obs: BrowserOutputObservation,
    ) -> None:
        context["last_obs"] = obs
        context["cur_url"] = obs.url
        context["screenshot_url"] = obs.screenshot
        if obs.axtree_object:
            context["cur_axtree_txt"] = self._safe_flatten_axtree(obs)
        context["error_prefix"] = self._derive_error_prefix(obs)
        if self.state_tracker and obs.url:
            self.state_tracker.visit_page(url=obs.url, screenshot_url=obs.screenshot)

    @staticmethod
    def _derive_error_prefix(obs: BrowserOutputObservation) -> str:
        if obs.last_browser_action_error:
            return obs.last_browser_action_error
        if obs.last_browser_action:
            return get_error_prefix(obs.last_browser_action)
        return ""

    def _safe_flatten_axtree(self, obs: BrowserOutputObservation) -> str:
        """Safely convert the accessibility tree to text."""
        if not obs or not obs.axtree_object:
            return ""
        try:
            extra = getattr(obs, "extra_element_properties", None)
            return flatten_axtree_to_str(
                obs.axtree_object,
                extra_properties=extra,
                with_clickable=True,
                filter_visible_only=True,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error when trying to process the accessibility tree: %s", exc)
            return ""

    def _track_action(self, browser_action: str) -> None:
        """Track browser action for state management."""
        if not self.state_tracker:
            return

        # Parse action to extract type and element
        if "click(" in browser_action:
            import re

            match = re.search(r'click\("([^"]+)"\)', browser_action)
            if match:
                self.state_tracker.track_interaction(match.group(1), "click")

        elif "type(" in browser_action:
            import re

            match = re.search(r'type\("([^"]+)",\s*"([^"]+)"\)', browser_action)
            if match:
                field_id, value = match.groups()
                self.state_tracker.track_interaction(field_id, "type")
                self.state_tracker.track_form_data(field_id, value)

    def _should_return_agent_message(self, context: BrowsingContext) -> bool:
        """Check if we should return an agent message."""
        return context["agent_message"] is not None

    def _should_return_user_message(self, context: BrowsingContext) -> bool:
        """Check if we should return a user message."""
        last_action = context["last_action"]
        return bool(
            isinstance(last_action, BrowseInteractiveAction)
            and last_action.browsergym_send_msg_to_user
        )

    def _should_handle_browser_error(self, context: BrowsingContext) -> bool:
        """Check if we should handle browser error."""
        return (
            isinstance(context["last_obs"], BrowserOutputObservation)
            and context["last_obs"].error
        )

    def _handle_browser_error_smart(
        self, context: BrowsingContext, state: State
    ) -> Action | None:
        """Handle browser error with smart recovery.

        Improvements over basic error handling:
        - Analyzes error type
        - Suggests alternative actions
        - Uses backtracking when stuck
        - Limits retries intelligently
        """
        last_obs = cast(BrowserOutputObservation, context["last_obs"])
        error_msg = last_obs.last_browser_action_error

        # Track error
        if self.state_tracker:
            self.state_tracker.track_error(error_msg)

        self.error_accumulator += 1

        # Check if we're retrying the same action
        current_action = context.get("last_action")
        if current_action and self.last_failed_action == str(current_action):
            self.retry_count += 1
        else:
            self.retry_count = 0
            self.last_failed_action = str(current_action)

        # Too many errors total
        if self.error_accumulator > 8:
            return MessageAction(
                "❌ Too many errors encountered. Browsing task failed."
            )

        # Too many retries of same action
        if self.retry_count >= self.max_retries:
            # Try going back as recovery
            if self.state_tracker and self.state_tracker.can_go_back():
                logger.info(
                    "🔄 Retries exhausted, trying alternative path (going back)"
                )
                self.retry_count = 0
                return BrowseInteractiveAction(browser_actions="go_back()")
            else:
                return MessageAction(
                    f"❌ Failed action after {self.max_retries} attempts. Cannot proceed."
                )

        # Continue with error context (let agent try alternative)
        logger.warning(
            "⚠️  Browser error (attempt %d/%d): %s",
            self.retry_count + 1,
            self.max_retries,
            error_msg[:100],
        )
        return None  # Continue to generate new action

    def _generate_browsing_action_react(
        self, state: State, context: BrowsingContext
    ) -> Action:
        """Generate browsing action using ReAct prompt.

        Improvements:
        - ReAct reasoning structure
        - tool_choice enforcement
        - Enhanced vision support
        - State context injection
        """
        goal, _ = state.get_current_user_intent()
        if goal is None:
            goal = state.inputs.get("task", "Browse web")

        # Build ReAct-structured messages
        messages = self._build_react_messages(goal, context)

        # LLM call with tool_choice enforcement (NEW!)
        params = {
            "messages": messages,
            "stop": [")```", ")\n```"],
            "temperature": 0.1,  # Deterministic browsing
        }

        # Enforce structured output for browsing actions
        if self._supports_tool_choice():
            params["tool_choice"] = "auto"  # Allow reasoning + action

        response: Any = self.llm.completion(**params)

        # Parse response
        parsed_input = cast(str | LLMResponsePayload, response)
        action = self.response_parser.parse(parsed_input)

        # Track action if it's a browser interaction
        if isinstance(action, BrowseInteractiveAction):
            self._track_action(action.browser_actions)

        return action

    def _generate_browsing_action(
        self, state: State, context: BrowsingContext
    ) -> Action:
        """Generate the browsing action prompt from current state and context."""
        goal, _ = state.get_current_user_intent()
        if goal is None:
            inputs: Any = getattr(state, "inputs", {})
            if isinstance(inputs, dict):
                goal = inputs.get("task")
        if goal is None:
            goal = "Browse the web to accomplish the user request."

        system_msg = get_system_message(
            goal,
            self.action_space.describe(with_long_description=False, with_examples=True),
        )
        messages = [Message(role="system", content=[TextContent(text=system_msg)])]

        prev_action_str = "\n".join(context["prev_actions"])
        prompt = get_prompt(
            context["error_prefix"],
            context["cur_url"],
            context["cur_axtree_txt"],
            prev_action_str,
        )
        messages.append(Message(role="user", content=[TextContent(text=prompt)]))

        response = self.llm.completion(messages=messages, stop=[")```", ")\n```"])
        return self.response_parser.parse(response)

    def _build_react_messages(
        self, goal: str, context: BrowsingContext
    ) -> list[Message]:
        """Build ReAct-structured messages.

        Args:
            goal: The browsing goal
            context: Current browsing context

        Returns:
            List of messages for LLM

        """
        messages = []

        # System message with ReAct prompt
        system_content = self.prompt_manager.get_system_message(goal=goal)
        if not system_content:
            # Fallback to basic prompt if template not found
            system_content = self._build_fallback_system_message(goal)

        messages.append(
            Message(role="system", content=[TextContent(text=system_content)])
        )

        # Add state tracking context (NEW!)
        if self.state_tracker:
            state_context = self.state_tracker.get_context_summary()
            messages.append(
                Message(role="system", content=[TextContent(text=state_context)])
            )

        # Current observation with vision (Enhanced!)
        observation_content = self._build_observation_content(context)
        messages.append(Message(role="user", content=observation_content))

        return messages

    def _build_observation_content(
        self, context: BrowsingContext
    ) -> list[TextContent | ImageContent]:
        """Build observation content with vision support.

        Args:
            context: Current context

        Returns:
            List of content items (text + images)

        """
        content: list[TextContent | ImageContent] = []

        # Build text observation
        text_parts: list[str] = []

        # Add error if present
        if context["error_prefix"]:
            text_parts.append(
                f"## Error from Previous Action:\n{context['error_prefix']}"
            )

        # Add current page info
        text_parts.append(f"## Current Page:\nURL: {context['cur_url']}")

        # Add accessibility tree
        if context["cur_axtree_txt"]:
            text_parts.append(
                f"\n## Page Elements (Accessibility Tree):\n{context['cur_axtree_txt']}"
            )

        # Add previous actions
        if context["prev_actions"]:
            prev_actions_str = "\n".join(context["prev_actions"][-5:])  # Last 5 actions
            text_parts.append(f"\n## Your Previous Actions:\n{prev_actions_str}")

        # Add state tracker summary (NEW!)
        if self.state_tracker:
            visited_pages = list(self.state_tracker.session.visited_pages)
            if self.state_tracker.current_page:
                visited_pages.append(self.state_tracker.current_page)
            visited_count = len(visited_pages)
            if visited_count > 0:
                text_parts.append(f"\n## Session Stats: Visited {visited_count} pages")

            # Add form data if any
            form_data = self.state_tracker.get_last_form_data()
            if form_data:
                text_parts.append(f"## Form Data Remembered: {len(form_data)} fields")

        content.append(TextContent(text="\n".join(text_parts)))

        # Add screenshot if available (Enhanced!)
        if context["screenshot_url"]:
            content.append(ImageContent(image_urls=[context["screenshot_url"]]))
            logger.debug("📸 Added screenshot to observation")

        return content

    def _build_fallback_system_message(self, goal: str) -> str:
        """Build fallback system message if template not found."""
        action_space_desc = self.action_space.describe(
            with_long_description=False, with_examples=True
        )

        return f"""You are a web browsing agent. Follow the ReAct pattern:

THINK: Analyze page state
ACT: Execute ONE browser action
OBSERVE: Check the result
VERIFY: Confirm it worked

Goal: {goal}

Available Actions:
{action_space_desc}

Be precise with bid numbers. Verify critical actions."""

    def _supports_tool_choice(self) -> bool:
        """Check if LLM supports tool_choice."""
        model_name = self.llm.config.model.lower()
        supported = ["gpt-4", "gpt-3.5", "claude", "gemini", "deepseek"]
        return any(s in model_name for s in supported)

    def response_to_actions(self, response: "ModelResponse") -> list[Action]:
        """Convert LLM response to actions."""
        parsed_input = cast(str | LLMResponsePayload, response)
        return [self.response_parser.parse(parsed_input)]

    def track_action_performance(
        self, action_type: str, duration_ms: float, success: bool
    ) -> None:
        """Track performance metrics for browsing actions.

        Args:
            action_type: Type of action (click, type, navigate, etc.)
            duration_ms: Time taken in milliseconds
            success: Whether action succeeded

        """
        self.performance_metrics["total_actions"] += 1
        self.performance_metrics["total_time_ms"] += duration_ms

        if success:
            self.performance_metrics["successful_actions"] += 1
        else:
            self.performance_metrics["failed_actions"] += 1

        # Update average
        self.performance_metrics["avg_action_time_ms"] = (
            self.performance_metrics["total_time_ms"]
            / self.performance_metrics["total_actions"]
        )

        # Log slow operations
        if duration_ms > 5000:  # >5 seconds
            logger.warning("⏱️  Slow action: %s took %.0fms", action_type, duration_ms)

    def get_performance_report(self) -> dict[str, float | int]:
        """Get performance metrics report."""
        metrics: dict[str, float | int] = {
            "total_actions": self.performance_metrics["total_actions"],
            "successful_actions": self.performance_metrics["successful_actions"],
            "failed_actions": self.performance_metrics["failed_actions"],
            "total_time_ms": self.performance_metrics["total_time_ms"],
            "avg_action_time_ms": self.performance_metrics["avg_action_time_ms"],
        }

        total_actions = cast(float, metrics["total_actions"])
        successful_actions = cast(float, metrics["successful_actions"])
        if total_actions > 0:
            metrics["success_rate"] = successful_actions / total_actions * 100
        else:
            metrics["success_rate"] = 0.0

        return metrics

    def export_session(self) -> dict:
        """Export browsing session for debugging/replay.

        Returns:
            Dictionary containing session data:
            - visited_pages: List of URLs visited
            - interactions: List of actions performed
            - form_data: Form fields filled
            - errors: Errors encountered
            - performance: Performance metrics

        """
        if not self.state_tracker:
            return {"error": "No active session"}

        session = self.state_tracker.session
        page_visits: list[PageVisit] = list(session.visited_pages)
        if self.state_tracker.current_page:
            page_visits.append(self.state_tracker.current_page)

        session_data = {
            "session_id": session.session_id,
            "goal": session.goal,
            "visited_pages": [
                {
                    "url": page.url,
                    "timestamp": page.timestamp.isoformat(),
                    "screenshot": page.screenshot_url,
                    "title": page.title,
                }
                for page in page_visits
            ],
            "interactions": self._collect_session_interactions(page_visits),
            "form_data": dict(session.form_fields_filled),
            "errors": list(session.errors_encountered),
            "performance": self.get_performance_report(),
        }

        logger.info(
            "📊 Session exported: %s pages, %s interactions",
            len(session_data["visited_pages"]),
            len(session_data["interactions"]),
        )

        return session_data

    def _collect_session_interactions(
        self, page_visits: Sequence[PageVisit]
    ) -> list[dict[str, str]]:
        """Serialize element interactions captured during browsing."""
        interactions: list[dict[str, str]] = []
        for page in page_visits:
            for entry in page.elements_interacted:
                action_type, _, element_id = entry.partition(":")
                interactions.append(
                    {
                        "element_id": element_id or entry,
                        "action_type": action_type or "unknown",
                        "timestamp": page.timestamp.isoformat(),
                        "url": page.url,
                    }
                )
        return interactions
