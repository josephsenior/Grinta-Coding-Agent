"""Tests for backend.utils.chunk_localizer — text chunking and LCS matching."""


from backend.utils.chunk_localizer import (
    Chunk,
    _create_chunks_from_raw_string,
    create_chunks,
    normalized_lcs,
    get_top_k_chunk_matches,
)


class TestChunkModel:
    """Tests for the Chunk model."""

    def test_chunk_creation(self):
        """Test basic chunk creation."""
        chunk = Chunk(text="hello\nworld", line_range=(1, 2))
        assert chunk.text == "hello\nworld"
        assert chunk.line_range == (1, 2)
        assert chunk.normalized_lcs == 0.0

    def test_chunk_with_lcs_score(self):
        """Test chunk with normalized_lcs score."""
        chunk = Chunk(text="test", line_range=(5, 5), normalized_lcs=0.75)
        assert chunk.normalized_lcs == 0.75

    def test_visualize_single_line(self):
        """Test visualize method with single line."""
        chunk = Chunk(text="hello", line_range=(3, 3))
        result = chunk.visualize()
        assert result == "3|hello\n"

    def test_visualize_multiple_lines(self):
        """Test visualize method with multiple lines."""
        chunk = Chunk(text="line1\nline2\nline3", line_range=(10, 12))
        result = chunk.visualize()
        assert result == "10|line1\n11|line2\n12|line3\n"

    def test_visualize_empty_line(self):
        """Test visualize with empty line."""
        chunk = Chunk(text="first\n\nlast", line_range=(1, 3))
        result = chunk.visualize()
        assert result == "1|first\n2|\n3|last\n"


class TestCreateChunksFromRawString:
    """Tests for _create_chunks_from_raw_string function."""

    def test_single_chunk_fits_size(self):
        """Test content that fits in a single chunk."""
        content = "line1\nline2\nline3"
        chunks = _create_chunks_from_raw_string(content, size=5)
        assert len(chunks) == 1
        assert chunks[0].text == "line1\nline2\nline3"
        assert chunks[0].line_range == (1, 3)

    def test_multiple_chunks(self):
        """Test content split into multiple chunks."""
        content = "\n".join([f"line{i}" for i in range(1, 11)])  # 10 lines
        chunks = _create_chunks_from_raw_string(content, size=3)
        assert len(chunks) == 4
        assert chunks[0].line_range == (1, 3)
        assert chunks[1].line_range == (4, 6)
        assert chunks[2].line_range == (7, 9)
        assert chunks[3].line_range == (10, 10)

    def test_exact_fit(self):
        """Test content that exactly fits chunk size."""
        content = "a\nb\nc\nd\ne\nf"  # 6 lines
        chunks = _create_chunks_from_raw_string(content, size=3)
        assert len(chunks) == 2
        assert chunks[0].text == "a\nb\nc"
        assert chunks[1].text == "d\ne\nf"

    def test_empty_content(self):
        """Test empty content."""
        chunks = _create_chunks_from_raw_string("", size=10)
        assert len(chunks) == 1
        assert chunks[0].text == ""
        assert chunks[0].line_range == (1, 1)

    def test_single_line(self):
        """Test single line content."""
        chunks = _create_chunks_from_raw_string("one line", size=5)
        assert len(chunks) == 1
        assert chunks[0].text == "one line"
        assert chunks[0].line_range == (1, 1)

    def test_chunk_size_one(self):
        """Test with chunk size of 1."""
        content = "a\nb\nc"
        chunks = _create_chunks_from_raw_string(content, size=1)
        assert len(chunks) == 3
        assert chunks[0].text == "a"
        assert chunks[1].text == "b"
        assert chunks[2].text == "c"


class TestCreateChunks:
    """Tests for create_chunks function."""

    def test_create_chunks_no_language(self):
        """Test create_chunks without language (raw string mode)."""
        text = "line1\nline2\nline3\nline4"
        chunks = create_chunks(text, size=2, language=None)
        assert len(chunks) == 2
        assert chunks[0].text == "line1\nline2"
        assert chunks[1].text == "line3\nline4"

    def test_create_chunks_default_size(self):
        """Test create_chunks with default size."""
        text = "\n".join([f"line{i}" for i in range(1, 51)])
        chunks = create_chunks(text)  # default size=100
        assert len(chunks) == 1

    def test_create_chunks_unsupported_language(self):
        """Test create_chunks with unsupported language falls back to raw."""
        text = "a\nb\nc\nd"
        chunks = create_chunks(text, size=2, language="unsupported_lang")
        # Should fall back to raw string chunking
        assert len(chunks) == 2

    def test_create_chunks_custom_size(self):
        """Test create_chunks with custom size."""
        text = "1\n2\n3\n4\n5"
        chunks = create_chunks(text, size=2, language=None)
        assert len(chunks) == 3


class TestNormalizedLcs:
    """Tests for normalized_lcs function."""

    def test_identical_strings(self):
        """Test LCS of identical strings."""
        score = normalized_lcs("hello world", "hello world")
        assert score == 1.0

    def test_completely_different(self):
        """Test LCS of completely different strings."""
        score = normalized_lcs("abcdef", "xyz")
        # LCS of "abcdef" and "xyz" is 0
        assert score == 0.0

    def test_partial_match(self):
        """Test LCS of partially matching strings."""
        chunk = "hello world"
        query = "hello"
        score = normalized_lcs(chunk, query)
        # All 5 chars of "hello" match, normalized by chunk length (11)
        assert score > 0.4
        assert score < 0.5

    def test_empty_chunk(self):
        """Test normalized_lcs with empty chunk."""
        score = normalized_lcs("", "query")
        assert score == 0.0

    def test_empty_query(self):
        """Test normalized_lcs with empty query."""
        score = normalized_lcs("chunk", "")
        assert score == 0.0

    def test_subsequence_match(self):
        """Test LCS with subsequence (not substring)."""
        chunk = "abcdefg"
        query = "ace"  # subsequence: a, c, e
        score = normalized_lcs(chunk, query)
        # 3 chars match out of 7
        assert score > 0.4
        assert score < 0.45

    def test_longer_query(self):
        """Test with query longer than chunk."""
        chunk = "short"
        query = "this is a much longer query"
        score = normalized_lcs(chunk, query)
        # Some chars will match, normalized by chunk length
        assert 0 <= score <= 1.0


class TestGetTopKChunkMatches:
    """Tests for get_top_k_chunk_matches function."""

    def test_single_best_match(self):
        """Test finding single best matching chunk."""
        text = "line1\nline2\nline3\nHELLO WORLD\nline5\nline6"
        query = "HELLO WORLD"
        chunks = get_top_k_chunk_matches(text, query, k=1, max_chunk_size=2)
        assert len(chunks) == 1
        assert "HELLO WORLD" in chunks[0].text
        assert chunks[0].normalized_lcs > 0.5

    def test_k_larger_than_chunks(self):
        """Test k larger than number of chunks."""
        text = "a\nb\nc"
        query = "b"
        chunks = get_top_k_chunk_matches(text, query, k=10, max_chunk_size=1)
        # Only 3 chunks possible
        assert len(chunks) == 3

    def test_sorted_by_score(self):
        """Test chunks are sorted by normalized_lcs (descending)."""
        text = "apple\nbanana\ncherry\napple pie\ndate\napple tart"
        query = "apple"
        chunks = get_top_k_chunk_matches(text, query, k=3, max_chunk_size=2)
        # Scores should be descending
        for i in range(len(chunks) - 1):
            assert chunks[i].normalized_lcs >= chunks[i + 1].normalized_lcs

    def test_exact_k_returned(self):
        """Test exactly k chunks returned when available."""
        text = "\n".join([f"line{i}" for i in range(20)])
        query = "line5"
        chunks = get_top_k_chunk_matches(text, query, k=5, max_chunk_size=3)
        assert len(chunks) == 5

    def test_all_scores_computed(self):
        """Test all chunks have normalized_lcs computed."""
        text = "a\nb\nc\nd\ne"
        query = "x"
        chunks = get_top_k_chunk_matches(text, query, k=10, max_chunk_size=1)
        for chunk in chunks:
            assert chunk.normalized_lcs >= 0.0

    def test_empty_query(self):
        """Test with empty query."""
        text = "some\ntext\nhere"
        chunks = get_top_k_chunk_matches(text, "", k=2, max_chunk_size=1)
        # All scores should be 0
        assert all(c.normalized_lcs == 0.0 for c in chunks)

    def test_default_parameters(self):
        """Test with default k=3 and max_chunk_size=100."""
        text = "\n".join([f"line{i}" for i in range(10)])
        query = "line3"
        chunks = get_top_k_chunk_matches(text, query)
        assert len(chunks) <= 3  # At most 3 returned

    def test_multiline_query(self):
        """Test matching with multiline query."""
        text = "def foo():\n    return 1\n\ndef bar():\n    return 2\n\ndef baz():\n    return 3"
        query = "def foo():\n    return 1"
        chunks = get_top_k_chunk_matches(text, query, k=1, max_chunk_size=2)
        assert len(chunks) == 1
        # Best match should contain the query
        assert chunks[0].normalized_lcs > 0.5
