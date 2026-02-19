"""Chunk localizer to help localize the most relevant chunks in a file.

This is primarily used to localize the most relevant chunks in a file
for a given query (e.g. edit draft produced by the agent).
"""

from __future__ import annotations

from pydantic import BaseModel
from rapidfuzz.distance import LCSseq

from backend.core.logger import forge_logger as logger


class Chunk(BaseModel):
    """Represent a snippet of text along with 1-based line range metadata."""

    text: str
    line_range: tuple[int, int]
    normalized_lcs: float = 0.0

    def visualize(self) -> str:
        """Render chunk with prefixed line numbers for display/debugging."""
        lines = self.text.split("\n")
        assert len(lines) == self.line_range[1] - self.line_range[0] + 1
        return "".join(
            (f"{self.line_range[0] + i}|{line}\n" for i, line in enumerate(lines))
        )


def _create_chunks_from_raw_string(content: str, size: int):
    """Create chunks from raw string content by splitting into fixed-size chunks.

    Args:
        content: The text content to chunk.
        size: The number of lines per chunk.

    Returns:
        list[Chunk]: List of chunks with line ranges.

    """
    lines = content.split("\n")
    ret = []
    for i in range(0, len(lines), size):
        _cur_lines = lines[i : i + size]
        ret.append(
            Chunk(text="\n".join(_cur_lines), line_range=(i + 1, i + len(_cur_lines)))
        )
    return ret


def create_chunks(
    text: str, size: int = 100, language: str | None = None
) -> list[Chunk]:
    """Split text into fixed-size chunks (optionally language-aware via tree-sitter).

    Resolve get_parser from the canonical module to ensure test monkeypatches are respected
    even under import duplication scenarios.
    """
    try:
        if language is not None:
            import importlib

            mod = importlib.import_module("backend.utils.chunk_localizer")
            parser_fn = getattr(mod, "get_parser")
            parser = parser_fn(language)
        else:
            parser = None
    except AttributeError:
        logger.debug("Language %s not supported. Falling back to raw string.", language)
        parser = None
    if parser is None:
        return _create_chunks_from_raw_string(text, size)
    msg = "Tree-sitter chunking not implemented yet."
    raise NotImplementedError(msg)


def normalized_lcs(chunk: str, query: str) -> float:
    """Calculate the normalized Longest Common Subsequence (LCS) to compare file chunk with the query (e.g. edit draft).

    We normalize Longest Common Subsequence (LCS) by the length of the chunk
    to check how **much** of the chunk is covered by the query.
    """
    if not chunk:
        return 0.0
    _score = LCSseq.similarity(chunk, query)
    return _score / len(chunk)


def get_top_k_chunk_matches(
    text: str, query: str, k: int = 3, max_chunk_size: int = 100
) -> list[Chunk]:
    """Get the top k chunks in the text that match the query.

    The query could be a string of draft code edits.

    Args:
        text: The text to search for the query.
        query: The query to search for in the text.
        k: The number of top chunks to return.
        max_chunk_size: The maximum number of lines in a chunk.

    """
    raw_chunks = create_chunks(text, max_chunk_size)
    chunks_with_lcs: list[Chunk] = [
        Chunk(
            text=chunk.text,
            line_range=chunk.line_range,
            normalized_lcs=normalized_lcs(chunk.text, query),
        )
        for chunk in raw_chunks
    ]
    sorted_chunks = sorted(
        chunks_with_lcs, key=lambda x: x.normalized_lcs, reverse=True
    )
    return sorted_chunks[:k]
