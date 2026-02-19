"""Browsing State Tracker - Remember Page State & Navigation History.

Tracks:
- Visited pages and URLs
- Form data entered
- Elements clicked
- Navigation path
- Page state snapshots
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.core.logger import forge_logger as logger


@dataclass
class PageVisit:
    """Record of a page visit."""

    url: str
    timestamp: datetime
    title: str | None = None
    elements_interacted: list[str] = field(default_factory=list)
    form_data: dict[str, str] = field(default_factory=dict)
    screenshot_url: str | None = None
    success: bool = True


@dataclass
class BrowsingSession:
    """Complete browsing session state."""

    session_id: str
    goal: str
    start_time: datetime
    current_url: str | None = None
    visited_pages: list[PageVisit] = field(default_factory=list)
    navigation_path: list[str] = field(default_factory=list)
    form_fields_filled: dict[str, str] = field(default_factory=dict)
    errors_encountered: list[str] = field(default_factory=list)


class BrowsingStateTracker:
    """Tracks browsing state across interactions.

    Features:
    - Page visit history
    - Form data memory
    - Element interaction tracking
    - Smart backtracking
    - Session persistence
    """

    def __init__(self, session_id: str, goal: str):
        """Initialize browsing state tracker.

        Args:
            session_id: Unique session identifier
            goal: The browsing goal

        """
        self.session = BrowsingSession(
            session_id=session_id, goal=goal, start_time=datetime.now()
        )
        self.current_page: PageVisit | None = None

        logger.info("🌐 Started browsing session: %s", session_id)

    def visit_page(
        self,
        url: str,
        title: str | None = None,
        screenshot_url: str | None = None,
    ) -> None:
        """Record a page visit.

        Args:
            url: The URL visited
            title: Page title (if available)
            screenshot_url: Screenshot URL (if available)

        """
        # Save previous page if exists
        if self.current_page:
            self.session.visited_pages.append(self.current_page)

        # Create new page visit
        self.current_page = PageVisit(
            url=url,
            timestamp=datetime.now(),
            title=title,
            screenshot_url=screenshot_url,
        )

        self.session.current_url = url
        self.session.navigation_path.append(url)

        logger.debug("📄 Visited: %s", url)

    def track_interaction(self, element_id: str, action_type: str) -> None:
        """Track element interaction.

        Args:
            element_id: The element interacted with
            action_type: Type of interaction (click, type, etc.)

        """
        if self.current_page:
            interaction = f"{action_type}:{element_id}"
            self.current_page.elements_interacted.append(interaction)
            logger.debug("👆 Interaction: %s", interaction)

    def track_form_data(self, field_name: str, value: str) -> None:
        """Track form data entry.

        Args:
            field_name: The form field name
            value: The value entered

        """
        if self.current_page:
            self.current_page.form_data[field_name] = value

        self.session.form_fields_filled[field_name] = value
        logger.debug("📝 Form data: %s = %s", field_name, value)

    def track_error(self, error_message: str) -> None:
        """Track an error.

        Args:
            error_message: The error message

        """
        self.session.errors_encountered.append(error_message)

        if self.current_page:
            self.current_page.success = False

        logger.warning("❌ Error: %s", error_message)

    def was_visited(self, url: str) -> bool:
        """Check if a URL was already visited."""
        return url in self.session.navigation_path

    def get_visited_count(self, url: str) -> int:
        """Get number of times a URL was visited."""
        return self.session.navigation_path.count(url)

    def get_last_form_data(self) -> dict[str, str]:
        """Get all form data entered in session."""
        return self.session.form_fields_filled.copy()

    def can_go_back(self) -> bool:
        """Check if we can navigate back."""
        return len(self.session.navigation_path) > 1

    def get_previous_url(self) -> str | None:
        """Get the previous URL in navigation path."""
        if len(self.session.navigation_path) >= 2:
            return self.session.navigation_path[-2]
        return None

    def get_context_summary(self) -> str:
        """Get summary of browsing context.

        Returns:
            Human-readable context summary

        """
        summary = "## Browsing Context:\n"
        summary += f"Goal: {self.session.goal}\n"
        summary += f"Current URL: {self.session.current_url}\n"
        summary += f"Pages visited: {len(self.session.visited_pages)}\n"

        if self.session.form_fields_filled:
            summary += "\n## Form Data Remembered:\n"
            for field, value in self.session.form_fields_filled.items():
                summary += (
                    f"- {field}: {value[:50]}{'...' if len(value) > 50 else ''}\n"
                )

        if self.session.errors_encountered:
            summary += f"\n## Recent Errors: {len(self.session.errors_encountered)}\n"
            for error in self.session.errors_encountered[-3:]:
                summary += f"- {error[:100]}...\n"

        return summary

    def get_stats(self) -> dict[str, Any]:
        """Get session statistics."""
        return {
            "pages_visited": len(self.session.visited_pages),
            "unique_urls": len(set(self.session.navigation_path)),
            "forms_filled": len(self.session.form_fields_filled),
            "errors": len(self.session.errors_encountered),
            "duration_seconds": (
                datetime.now() - self.session.start_time
            ).total_seconds(),
        }
