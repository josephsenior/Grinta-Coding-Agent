"""Unit tests for backend.utils.chunk_localizer — chunking & LCS matching."""

from __future__ import annotations

import pytest

from backend.utils.chunk_localizer import (
    Chunk,
    _create_chunks_from_raw_string,
    create_chunks,
    get_top_k_chunk_matches,
    normalized_lcs,
)


# ---------------------------------------------------------------------------
# Chunk model
# ---------------------------------------------------------------------------


class TestChunk:
    def test_basic(self):
        c = Chunk(text="hello\nworld", line_range=(1, 2))
        assert c.text == "hello\nworld"
        assert c.line_range == (1, 2)
        assert c.normalized_lcs == 0.0

    def test_visualize(self):
        c = Chunk(text="line1\nline2", line_range=(5, 6))
        vis = c.visualize()
        assert "5|line1" in vis
        assert "6|line2" in vis


# ---------------------------------------------------------------------------
# _create_chunks_from_raw_string
# ---------------------------------------------------------------------------


class TestCreateChunksRaw:
    def test_single_chunk(self):
        text = "a\nb\nc"
        chunks = _create_chunks_from_raw_string(text, size=10)
        assert len(chunks) == 1
        assert chunks[0].line_range == (1, 3)

    def test_multiple_chunks(self):
        lines = [f"line{i}" for i in range(10)]
        text = "\n".join(lines)
        chunks = _create_chunks_from_raw_string(text, size=3)
        assert len(chunks) == 4  # 10 lines / 3 = 4 chunks (3+3+3+1)
        assert chunks[0].line_range == (1, 3)
        assert chunks[-1].line_range == (10, 10)

    def test_empty_string(self):
        chunks = _create_chunks_from_raw_string("", size=5)
        assert len(chunks) == 1
        assert chunks[0].text == ""

    def test_exact_division(self):
        text = "a\nb\nc\nd"
        chunks = _create_chunks_from_raw_string(text, size=2)
        assert len(chunks) == 2
        assert chunks[0].line_range == (1, 2)
        assert chunks[1].line_range == (3, 4)


# ---------------------------------------------------------------------------
# create_chunks (with language=None fallback)
# ---------------------------------------------------------------------------


class TestCreateChunks:
    def test_defaults_to_raw(self):
        text = "a\nb\nc"
        chunks = create_chunks(text, size=5)
        assert len(chunks) == 1

    def test_custom_size(self):
        lines = "\n".join(str(i) for i in range(20))
        chunks = create_chunks(lines, size=5)
        assert len(chunks) == 4


# ---------------------------------------------------------------------------
# normalized_lcs
# ---------------------------------------------------------------------------


class TestNormalizedLCS:
    def test_identical(self):
        score = normalized_lcs("abc", "abc")
        assert score == pytest.approx(1.0)

    def test_no_overlap(self):
        score = normalized_lcs("aaa", "zzz")
        assert score == 0.0

    def test_empty_chunk(self):
        assert normalized_lcs("", "anything") == 0.0

    def test_partial_overlap(self):
        score = normalized_lcs("abcdef", "ace")
        assert 0.0 < score < 1.0

    def test_long_query_covers_chunk(self):
        chunk = "def"
        query = "abcdefghij"
        score = normalized_lcs(chunk, query)
        assert score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# get_top_k_chunk_matches
# ---------------------------------------------------------------------------


class TestGetTopKChunkMatches:
    def test_returns_k_results(self):
        text = "\n".join(f"line_{i}" for i in range(30))
        results = get_top_k_chunk_matches(text, query="line_5", k=2, max_chunk_size=10)
        assert len(results) == 2

    def test_best_match_first(self):
        text = "alpha\nbeta\ngamma\ndelta"
        results = get_top_k_chunk_matches(text, query="gamma", k=4, max_chunk_size=1)
        # The chunk containing "gamma" should have the highest score
        assert results[0].normalized_lcs >= results[-1].normalized_lcs

    def test_single_chunk(self):
        text = "hello world"
        results = get_top_k_chunk_matches(text, query="hello", k=5, max_chunk_size=100)
        assert len(results) == 1

    def test_scored(self):
        text = "foo\nbar\nbaz"
        results = get_top_k_chunk_matches(text, query="bar", k=3, max_chunk_size=1)
        for chunk in results:
            assert isinstance(chunk.normalized_lcs, float)
