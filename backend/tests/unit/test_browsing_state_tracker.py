"""Tests for backend.engines.navigator.state_tracker — BrowsingStateTracker."""

from __future__ import annotations

from datetime import datetime

from backend.engines.navigator.state_tracker import (
    BrowsingSession,
    BrowsingStateTracker,
    PageVisit,
)


# ── PageVisit dataclass ──────────────────────────────────────────────


class TestPageVisit:
    def test_defaults(self):
        pv = PageVisit(url="https://example.com", timestamp=datetime(2025, 1, 1))
        assert pv.title is None
        assert pv.elements_interacted == []
        assert pv.form_data == {}
        assert pv.screenshot_url is None
        assert pv.success is True

    def test_custom(self):
        pv = PageVisit(
            url="https://test.com",
            timestamp=datetime(2025, 6, 1),
            title="Test Page",
            elements_interacted=["click:btn1"],
            form_data={"user": "admin"},
            screenshot_url="s3://bucket/img.png",
            success=False,
        )
        assert pv.title == "Test Page"
        assert len(pv.elements_interacted) == 1
        assert pv.form_data["user"] == "admin"
        assert pv.success is False


# ── BrowsingSession dataclass ────────────────────────────────────────


class TestBrowsingSession:
    def test_defaults(self):
        bs = BrowsingSession(
            session_id="s1", goal="Buy item", start_time=datetime(2025, 1, 1)
        )
        assert bs.current_url is None
        assert bs.visited_pages == []
        assert bs.navigation_path == []
        assert bs.form_fields_filled == {}
        assert bs.errors_encountered == []


# ── BrowsingStateTracker ─────────────────────────────────────────────


class TestBrowsingStateTracker:
    def _make_tracker(self) -> BrowsingStateTracker:
        return BrowsingStateTracker(session_id="test-1", goal="Find documentation")

    def test_init(self):
        t = self._make_tracker()
        assert t.session.session_id == "test-1"
        assert t.session.goal == "Find documentation"
        assert t.current_page is None

    def test_visit_page(self):
        t = self._make_tracker()
        t.visit_page("https://example.com", title="Home")
        assert t.current_page is not None
        assert t.current_page.url == "https://example.com"
        assert t.current_page.title == "Home"
        assert t.session.current_url == "https://example.com"
        assert "https://example.com" in t.session.navigation_path

    def test_visit_multiple_pages(self):
        t = self._make_tracker()
        t.visit_page("https://a.com")
        t.visit_page("https://b.com")
        # Previous page saved to visited_pages
        assert len(t.session.visited_pages) == 1
        assert t.session.visited_pages[0].url == "https://a.com"
        assert t.current_page.url == "https://b.com"

    def test_track_interaction(self):
        t = self._make_tracker()
        t.visit_page("https://example.com")
        t.track_interaction("btn-submit", "click")
        assert "click:btn-submit" in t.current_page.elements_interacted

    def test_track_interaction_no_page(self):
        t = self._make_tracker()
        # No current page — should not raise
        t.track_interaction("btn", "click")

    def test_track_form_data(self):
        t = self._make_tracker()
        t.visit_page("https://login.com")
        t.track_form_data("username", "admin")
        assert t.current_page.form_data["username"] == "admin"
        assert t.session.form_fields_filled["username"] == "admin"

    def test_track_error(self):
        t = self._make_tracker()
        t.visit_page("https://broken.com")
        t.track_error("404 Not Found")
        assert "404 Not Found" in t.session.errors_encountered
        assert t.current_page.success is False

    def test_track_error_no_page(self):
        t = self._make_tracker()
        t.track_error("Connection refused")
        assert "Connection refused" in t.session.errors_encountered

    def test_was_visited(self):
        t = self._make_tracker()
        assert t.was_visited("https://x.com") is False
        t.visit_page("https://x.com")
        assert t.was_visited("https://x.com") is True

    def test_get_visited_count(self):
        t = self._make_tracker()
        t.visit_page("https://x.com")
        t.visit_page("https://y.com")
        t.visit_page("https://x.com")
        assert t.get_visited_count("https://x.com") == 2
        assert t.get_visited_count("https://y.com") == 1
        assert t.get_visited_count("https://z.com") == 0

    def test_get_last_form_data_is_copy(self):
        t = self._make_tracker()
        t.visit_page("https://form.com")
        t.track_form_data("email", "a@b.com")
        data = t.get_last_form_data()
        data["email"] = "modified"
        assert t.session.form_fields_filled["email"] == "a@b.com"

    def test_can_go_back(self):
        t = self._make_tracker()
        assert t.can_go_back() is False
        t.visit_page("https://a.com")
        assert t.can_go_back() is False
        t.visit_page("https://b.com")
        assert t.can_go_back() is True

    def test_get_previous_url(self):
        t = self._make_tracker()
        assert t.get_previous_url() is None
        t.visit_page("https://a.com")
        assert t.get_previous_url() is None
        t.visit_page("https://b.com")
        assert t.get_previous_url() == "https://a.com"

    def test_get_context_summary(self):
        t = self._make_tracker()
        t.visit_page("https://example.com")
        t.track_form_data("user", "admin")
        t.track_error("Timeout")
        summary = t.get_context_summary()
        assert "Find documentation" in summary
        assert "https://example.com" in summary
        assert "user" in summary
        assert "Timeout" in summary

    def test_get_stats(self):
        t = self._make_tracker()
        t.visit_page("https://a.com")
        t.visit_page("https://b.com")
        t.track_form_data("f", "v")
        t.track_error("err")
        stats = t.get_stats()
        assert stats["pages_visited"] == 1  # current_page not appended yet
        assert stats["unique_urls"] == 2
        assert stats["forms_filled"] == 1
        assert stats["errors"] == 1
        assert stats["duration_seconds"] >= 0
