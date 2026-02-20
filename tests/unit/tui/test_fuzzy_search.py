"""Unit tests for fuzzy search scoring in tui.screens.home."""

from __future__ import annotations

from types import SimpleNamespace


from tui.screens.home import HomeScreen, _fuzzy_subsequence_score


# ---------------------------------------------------------------------------
# _fuzzy_subsequence_score (module-level)
# ---------------------------------------------------------------------------


class TestFuzzySubsequenceScore:
    def test_empty_query_returns_zero(self):
        assert _fuzzy_subsequence_score("", "hello") == 0.0

    def test_empty_target_returns_zero(self):
        assert _fuzzy_subsequence_score("abc", "") == 0.0

    def test_both_empty_returns_zero(self):
        assert _fuzzy_subsequence_score("", "") == 0.0

    def test_exact_match_high_score(self):
        score = _fuzzy_subsequence_score("hello", "hello")
        assert score >= 45.0  # Minimal gap penalty

    def test_subsequence_present(self):
        """Characters appear in order — should score > 0."""
        score = _fuzzy_subsequence_score("abc", "axbxc")
        assert score > 0

    def test_subsequence_absent(self):
        """Not all chars found in order — score 0."""
        assert _fuzzy_subsequence_score("xyz", "hello") == 0.0

    def test_gap_penalty_reduces_score(self):
        close = _fuzzy_subsequence_score("abc", "abc")
        far = _fuzzy_subsequence_score("abc", "a---b---c")
        assert close > far

    def test_minimum_score_when_matched(self):
        """Even with large gaps the score should be >= 5.0 per implementation."""
        score = _fuzzy_subsequence_score("ac", "a" + "x" * 100 + "c")
        assert score >= 5.0

    def test_single_char_query(self):
        score = _fuzzy_subsequence_score("a", "apple")
        assert score > 0

    def test_case_sensitivity(self):
        """The function operates on raw strings — caller lowercases."""
        # Same-case should match
        assert _fuzzy_subsequence_score("abc", "abc") > 0
        # Different case won't match since no internal lowering
        assert _fuzzy_subsequence_score("ABC", "abc") == 0.0


# ---------------------------------------------------------------------------
# HomeScreen._fuzzy_match_score (static method)
# ---------------------------------------------------------------------------


def _make_conv(title: str = "", status: str = "running", cid: str = "conv-001"):
    """Build a minimal ConversationInfo-like object for testing."""
    return SimpleNamespace(title=title, status=status, conversation_id=cid)


class TestFuzzyMatchScore:
    def test_exact_title_match_returns_100(self):
        conv = _make_conv(title="fix login bug")
        assert HomeScreen._fuzzy_match_score("fix login bug", conv) == 100.0

    def test_substring_title_match_returns_100(self):
        conv = _make_conv(title="fix login bug in auth module")
        assert HomeScreen._fuzzy_match_score("login bug", conv) == 100.0

    def test_status_match_returns_80(self):
        conv = _make_conv(title="something else", status="running")
        assert HomeScreen._fuzzy_match_score("running", conv) == 80.0

    def test_cid_match_returns_70(self):
        conv = _make_conv(title="task", cid="abc-123-def")
        assert HomeScreen._fuzzy_match_score("abc-123", conv) == 70.0

    def test_fuzzy_subsequence_returns_positive(self):
        conv = _make_conv(title="refactor database layer")
        score = HomeScreen._fuzzy_match_score("rdl", conv)
        assert 0 < score <= 50

    def test_all_words_match_returns_high(self):
        conv = _make_conv(
            title="database migration complete", status="done", cid="id-1"
        )
        # Each word found somewhere across title/status/cid
        score = HomeScreen._fuzzy_match_score("database done", conv)
        # "database" in title (substring → 100), or "database done" not substring → word match
        assert score >= 60.0

    def test_partial_word_match(self):
        conv = _make_conv(title="database migration", status="ok")
        score = HomeScreen._fuzzy_match_score("database upload missing", conv)
        # Only "database" matches out of 3 words → proportional ~10
        assert 0 < score < 60

    def test_no_match_returns_zero(self):
        conv = _make_conv(title="abc", status="done", cid="x")
        assert HomeScreen._fuzzy_match_score("zzzzz", conv) == 0.0

    def test_case_insensitive_matching(self):
        conv = _make_conv(title="Fix Login Bug")
        assert HomeScreen._fuzzy_match_score("FIX LOGIN", conv) == 100.0

    def test_empty_query(self):
        conv = _make_conv(title="anything")
        score = HomeScreen._fuzzy_match_score("", conv)
        # Empty query — no word match, no subsequence
        # All words matched vacuously → 60 or 0 depending on impl
        # With words=[], matched=0 len(words)=0 → the all-words branch is skipped
        assert score >= 0  # Just don't crash
