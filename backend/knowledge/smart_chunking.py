"""Smart chunking strategies based on file type."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from backend.persistence.data_models.knowledge_base import DocumentChunk

logger = logging.getLogger(__name__)


class SmartChunker:
    """Selects optimal chunking strategy based on file type."""

    CHUNK_SIZES = {
        'code': 4000,
        'markdown': 3000,
        'json': 2500,
        'yaml': 2500,
        'text': 4000,
    }

    CHUNK_OVERLAPS = {
        'code': 800,
        'markdown': 500,
        'json': 300,
        'yaml': 300,
        'text': 800,
    }

    def __init__(self, max_chunk_bytes: int = 4000, overlap: int = 800):
        self.default_max = max_chunk_bytes
        self.default_overlap = overlap

    def get_file_type(self, filename: str | None) -> str:
        """Determine file type from filename."""
        if not filename:
            return 'text'
        ext = Path(filename).suffix.lower()
        code_exts = {
            '.py',
            '.js',
            '.ts',
            '.jsx',
            '.tsx',
            '.java',
            '.go',
            '.rs',
            '.cpp',
            '.c',
            '.h',
            '.cs',
            '.rb',
            '.php',
            '.swift',
            '.kt',
            '.scala',
        }
        md_exts = {'.md', '.markdown', '.rst', '.txt'}
        json_exts = {'.json', '.jsonc'}
        yaml_exts = {'.yaml', '.yml', '.toml'}

        if ext in code_exts:
            return 'code'
        if ext in md_exts:
            return 'markdown'
        if ext in json_exts:
            return 'json'
        if ext in yaml_exts:
            return 'yaml'
        return 'text'

    def get_chunk_params(self, filename: str | None) -> tuple[int, int]:
        """Get chunk size and overlap for file type."""
        ftype = self.get_file_type(filename)
        size = self.CHUNK_SIZES.get(ftype, self.default_max)
        overlap = self.CHUNK_OVERLAPS.get(ftype, self.default_overlap)
        return size, overlap

    def chunk_markdown(
        self, content: str, document_id: str, metadata: dict[str, Any] | None
    ) -> list[DocumentChunk]:
        """Chunk markdown by headers and logical sections."""
        chunks: list[DocumentChunk] = []
        lines = content.split('\n')
        current_section: list[str] = []
        current_size = 0
        chunk_index = 0
        max_size, overlap = self.get_chunk_params('.md')

        for line in lines:
            is_header = bool(re.match(r'^#{1,6}\s', line))
            header_level = len(line) - len(line.lstrip('#')) if is_header else 0

            if is_header and header_level <= 2 and current_section:
                chunk_index, current_section, current_size = self._flush_section(
                    chunks,
                    current_section,
                    chunk_index,
                    document_id,
                    metadata,
                    'markdown_header',
                    max_size,
                )
                current_section = [line]
                current_size = len(line)
            elif current_size + len(line) + 1 > max_size and current_section:
                chunk_index, current_section, current_size = self._flush_section(
                    chunks,
                    current_section,
                    chunk_index,
                    document_id,
                    metadata,
                    'markdown_body',
                    max_size,
                    overlap,
                    next_line=line,
                )
            else:
                current_section.append(line)
                current_size += len(line) + 1

        if current_section:
            self._append_chunk(
                chunks,
                current_section,
                chunk_index,
                document_id,
                metadata,
                'markdown_body',
            )

        return chunks

    def _flush_section(
        self,
        chunks: list[DocumentChunk],
        section: list[str],
        chunk_index: int,
        document_id: str,
        metadata: dict[str, Any] | None,
        section_type: str,
        max_size: int,
        overlap: int = 0,
        next_line: str | None = None,
    ) -> tuple[int, list[str], int]:
        chunk_text = '\n'.join(section).strip()
        if chunk_text:
            self._append_chunk(
                chunks, section, chunk_index, document_id, metadata, section_type
            )
            chunk_index += 1
        if next_line is not None and overlap > 0:
            overlap_lines = section[-overlap // 50 :]
            new_section = overlap_lines + [next_line]
            new_size = sum(len(line_item) + 1 for line_item in new_section)
            return chunk_index, new_section, new_size
        return chunk_index, [], 0

    def _append_chunk(
        self,
        chunks: list[DocumentChunk],
        section: list[str],
        chunk_index: int,
        document_id: str,
        metadata: dict[str, Any] | None,
        section_type: str,
    ) -> None:
        chunk_text = '\n'.join(section).strip()
        if chunk_text:
            chunks.append(
                DocumentChunk(
                    id=f'{document_id}_chunk_{chunk_index}',
                    document_id=document_id,
                    chunk_index=chunk_index,
                    content=chunk_text,
                    metadata={**(metadata or {}), '_section_type': section_type},
                )
            )

    def chunk_json(
        self, content: str, document_id: str, metadata: dict[str, Any] | None
    ) -> list[DocumentChunk]:
        """Chunk JSON by top-level keys and array items."""
        chunks: list[DocumentChunk] = []
        chunk_index = 0
        max_size, _ = self.get_chunk_params('.json')

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return self.chunk_text_fallback(content, document_id, metadata)

        def chunk_value(key: str, value: Any, path: str) -> list[DocumentChunk]:
            nonlocal chunk_index
            result = []
            serialized = json.dumps(value, indent=2)
            if len(serialized) <= max_size:
                result.append(
                    DocumentChunk(
                        id=f'{document_id}_chunk_{chunk_index}',
                        document_id=document_id,
                        chunk_index=chunk_index,
                        content=f'# {key}\n\n{serialized}',
                        metadata={
                            **(metadata or {}),
                            '_json_path': f'{path}.{key}',
                            '_section_type': 'json_object',
                        },
                    )
                )
                chunk_index += 1
            elif isinstance(value, dict):
                for k, v in value.items():
                    result.extend(chunk_value(k, v, f'{path}.{key}'))
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    result.extend(chunk_value(f'{key}[{i}]', item, f'{path}.{key}'))
            return result

        if isinstance(data, dict):
            for key, value in data.items():
                chunks.extend(chunk_value(key, value, '$'))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                chunks.extend(chunk_value(f'[{i}]', item, '$'))

        return chunks

    def chunk_yaml(
        self, content: str, document_id: str, metadata: dict[str, Any] | None
    ) -> list[DocumentChunk]:
        """Chunk YAML by top-level keys and list items."""
        chunks: list[DocumentChunk] = []
        chunk_index = 0
        max_size, _ = self.get_chunk_params('.yaml')
        lines = content.split('\n')
        current_doc: list[str] = []
        current_size = 0

        for line in lines:
            is_document_start = bool(re.match(r'^---\s*$', line))

            if is_document_start and current_doc:
                chunk_index = self._flush_yaml_section(
                    chunks,
                    current_doc,
                    chunk_index,
                    document_id,
                    metadata,
                    'yaml_document',
                )
                current_doc = []
                current_size = 0

            if current_size + len(line) + 1 > max_size and current_doc:
                chunk_index = self._flush_yaml_section(
                    chunks,
                    current_doc,
                    chunk_index,
                    document_id,
                    metadata,
                    'yaml_body',
                )
                current_doc = []
                current_size = 0

            current_doc.append(line)
            current_size += len(line) + 1

        if current_doc:
            self._append_chunk(
                chunks, current_doc, chunk_index, document_id, metadata, 'yaml_body'
            )

        return (
            chunks
            if chunks
            else self.chunk_text_fallback(content, document_id, metadata)
        )

    def _flush_yaml_section(
        self,
        chunks: list[DocumentChunk],
        section: list[str],
        chunk_index: int,
        document_id: str,
        metadata: dict[str, Any] | None,
        section_type: str,
    ) -> int:
        chunk_text = '\n'.join(section).strip()
        if chunk_text:
            self._append_chunk(
                chunks, section, chunk_index, document_id, metadata, section_type
            )
            return chunk_index + 1
        return chunk_index

    def chunk_text_fallback(
        self, content: str, document_id: str, metadata: dict[str, Any] | None
    ) -> list[DocumentChunk]:
        """Basic sliding window for text files."""
        max_size, overlap = self.get_chunk_params('.txt')
        return self._sliding_window_chunk(
            content, document_id, metadata, chunk_size=max_size, chunk_overlap=overlap
        )

    # ------------------------------------------------------------------
    # Code chunking (AST-aware via tree-sitter, falling back to sliding
    # window).  These methods were consolidated here from
    # KnowledgeBaseManager so that SmartChunker is the single source of
    # truth for all chunking strategies.
    # ------------------------------------------------------------------

    def chunk_code(
        self,
        content: str,
        document_id: str,
        filename: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[DocumentChunk]:
        """AST-aware chunking for code files.

        Tries tree-sitter to find symbol boundaries.  Falls back to
        sliding-window chunking if tree-sitter is unavailable or the
        language is unsupported.
        """
        boundaries = self._collect_ast_boundaries(content, filename)
        if boundaries is not None:
            chunks = self._merge_boundaries_into_chunks(
                content, document_id, metadata, boundaries
            )
            if chunks:
                for c in chunks:
                    c.metadata.pop('_byte_start', None)
                return chunks

        # Fallback: character-based sliding window
        max_size, overlap = self.get_chunk_params(filename)
        return self._sliding_window_chunk(
            content, document_id, metadata, chunk_size=max_size, chunk_overlap=overlap
        )

    def _collect_ast_boundaries(
        self, content: str, filename: str
    ) -> list[tuple[int, int]] | None:
        """Parse content with tree-sitter and return symbol boundaries, or None.

        Looks up language by file extension, parses with tree-sitter, and
        collects (start_byte, end_byte) for top-level function/class/module
        nodes.  Returns None if tree-sitter is unavailable or the language
        is unsupported.
        """
        try:
            from backend.utils.treesitter_editor import (
                LANGUAGE_EXTENSIONS,
                TREE_SITTER_AVAILABLE,
                _get_parser,
            )
        except ImportError:
            return None

        if not TREE_SITTER_AVAILABLE or _get_parser is None:
            return None

        import os

        ext = os.path.splitext(filename)[1].lower()
        lang = LANGUAGE_EXTENSIONS.get(ext)
        if not lang:
            return None

        try:
            parser = _get_parser(lang)
            tree = parser.parse(content.encode('utf-8'))
        except Exception:
            return None

        keywords = (
            'function',
            'method',
            'class',
            'module',
            'interface',
            'struct',
            'enum',
            'impl',
            'trait',
            'declaration',
            'definition',
        )
        boundaries = [
            (child.start_byte, child.end_byte)
            for child in tree.root_node.children
            if any(kw in child.type for kw in keywords)
        ]
        return boundaries if boundaries else None

    def _merge_handle_oversized_segment(
        self,
        segment: str,
        document_id: str,
        metadata: dict[str, Any] | None,
        max_chunk_bytes: int,
        chunk_index: int,
    ) -> tuple[list[DocumentChunk], int]:
        """Split oversized segment via sliding window.

        Returns (new_chunks, new_index).
        """
        sub_chunks = self._sliding_window_chunk(
            segment,
            document_id,
            metadata,
            chunk_size=max_chunk_bytes,
            start_index=chunk_index,
        )
        return sub_chunks, chunk_index + len(sub_chunks)

    def _merge_append_or_extend_chunk(
        self,
        chunks: list[DocumentChunk],
        content: str,
        document_id: str,
        metadata: dict[str, Any] | None,
        max_chunk_bytes: int,
        overlap_bytes: int,
        chunk_index: int,
        last_start: int,
        current_start: int,
        sym_end: int,
    ) -> int:
        """Append new chunk or extend last chunk.

        Returns updated chunk_index.
        """
        if chunks:
            merged_bytes = len((content[last_start:sym_end]).encode('utf-8'))
            if merged_bytes <= max_chunk_bytes:
                last = chunks[-1]
                merged = content[last_start:sym_end]
                chunks[-1] = DocumentChunk(
                    document_id=document_id,
                    chunk_index=last.chunk_index,
                    content=merged,
                    metadata={**(metadata or {}), '_byte_start': last_start},
                )
                return chunk_index
        overlap_start = (
            max(0, current_start - overlap_bytes) if chunk_index > 0 else current_start
        )
        chunk_text = content[overlap_start:sym_end]
        if chunk_text.strip():
            chunks.append(
                DocumentChunk(
                    document_id=document_id,
                    chunk_index=chunk_index,
                    content=chunk_text,
                    metadata={**(metadata or {}), '_byte_start': overlap_start},
                )
            )
            return chunk_index + 1
        return chunk_index

    def _merge_boundaries_into_chunks(
        self,
        content: str,
        document_id: str,
        metadata: dict[str, Any] | None,
        boundaries: list[tuple[int, int]],
    ) -> list[DocumentChunk]:
        """Merge symbol boundaries into chunks respecting max size.

        Each boundary is (byte_start, byte_end).  Segments exceeding
        max_chunk_bytes are split via sliding window.  Small adjacent
        segments are merged with overlap.
        """
        max_chunk_bytes = 4000
        overlap_bytes = 800
        chunks: list[DocumentChunk] = []
        chunk_index = 0
        current_start = 0

        for sym_start, sym_end in boundaries:
            segment = content[current_start:sym_end]
            segment_bytes = len(segment.encode('utf-8'))

            if segment_bytes > max_chunk_bytes and chunks:
                sub_chunks, chunk_index = self._merge_handle_oversized_segment(
                    segment, document_id, metadata, max_chunk_bytes, chunk_index
                )
                chunks.extend(sub_chunks)
                current_start = sym_end
                continue

            last_start = int(chunks[-1].metadata.get('_byte_start', 0) if chunks else 0)
            chunk_index = self._merge_append_or_extend_chunk(
                chunks,
                content,
                document_id,
                metadata,
                max_chunk_bytes,
                overlap_bytes,
                chunk_index,
                last_start,
                current_start,
                sym_end,
            )
            current_start = sym_end

        if current_start < len(content):
            trailing = content[current_start:]
            if trailing.strip():
                chunks.append(
                    DocumentChunk(
                        document_id=document_id,
                        chunk_index=chunk_index,
                        content=trailing,
                        metadata=metadata or {},
                    )
                )
        return chunks

    def _sliding_window_chunk(
        self,
        content: str,
        document_id: str,
        metadata: dict[str, Any] | None = None,
        chunk_size: int = 4000,
        chunk_overlap: int = 800,
        start_index: int = 0,
    ) -> list[DocumentChunk]:
        """Character-based sliding window chunking (universal fallback)."""
        chunks: list[DocumentChunk] = []
        start = 0
        chunk_index = start_index

        while start < len(content):
            end = start + chunk_size
            chunk_text = content[start:end]

            if chunk_text.strip():
                chunks.append(
                    DocumentChunk(
                        document_id=document_id,
                        chunk_index=chunk_index,
                        content=chunk_text,
                        metadata=metadata or {},
                    )
                )
                chunk_index += 1

            start = end - chunk_overlap

        return chunks

