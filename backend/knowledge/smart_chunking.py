"""Smart chunking strategies based on file type."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.persistence.data_models.knowledge_base import DocumentChunk


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
                if current_size > 0:
                    chunk_text = '\n'.join(current_section).strip()
                    if chunk_text:
                        chunks.append(
                            DocumentChunk(
                                id=f'{document_id}_chunk_{chunk_index}',
                                document_id=document_id,
                                chunk_index=chunk_index,
                                content=chunk_text,
                                metadata={
                                    **(metadata or {}),
                                    '_section_type': 'markdown_header',
                                },
                            )
                        )
                        chunk_index += 1
                current_section = [line]
                current_size = len(line)
            else:
                if current_size + len(line) + 1 > max_size and current_section:
                    chunk_text = '\n'.join(current_section).strip()
                    if chunk_text:
                        chunks.append(
                            DocumentChunk(
                                id=f'{document_id}_chunk_{chunk_index}',
                                document_id=document_id,
                                chunk_index=chunk_index,
                                content=chunk_text,
                                metadata={
                                    **(metadata or {}),
                                    '_section_type': 'markdown_body',
                                },
                            )
                        )
                        chunk_index += 1
                        overlap_lines = current_section[-overlap // 50 :]
                        current_section = overlap_lines + [line]
                        current_size = sum(
                            len(line_item) + 1 for line_item in current_section
                        )
                else:
                    current_section.append(line)
                    current_size += len(line) + 1

        if current_section:
            chunk_text = '\n'.join(current_section).strip()
            if chunk_text:
                chunks.append(
                    DocumentChunk(
                        id=f'{document_id}_chunk_{chunk_index}',
                        document_id=document_id,
                        chunk_index=chunk_index,
                        content=chunk_text,
                        metadata={**(metadata or {}), '_section_type': 'markdown_body'},
                    )
                )

        return chunks

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

        for i, line in enumerate(lines):
            is_document_start = bool(re.match(r'^---\s*$', line))
            bool(re.match(r'^-\s+', line))
            bool(re.match(r'^[\w\-]+:\s', line))

            if is_document_start and current_doc:
                chunk_text = '\n'.join(current_doc).strip()
                if chunk_text:
                    chunks.append(
                        DocumentChunk(
                            id=f'{document_id}_chunk_{chunk_index}',
                            document_id=document_id,
                            chunk_index=chunk_index,
                            content=chunk_text,
                            metadata={
                                **(metadata or {}),
                                '_section_type': 'yaml_document',
                            },
                        )
                    )
                    chunk_index += 1
                current_doc = []
                current_size = 0

            if current_size + len(line) + 1 > max_size and current_doc:
                chunk_text = '\n'.join(current_doc).strip()
                if chunk_text:
                    chunks.append(
                        DocumentChunk(
                            id=f'{document_id}_chunk_{chunk_index}',
                            document_id=document_id,
                            chunk_index=chunk_index,
                            content=chunk_text,
                            metadata={**(metadata or {}), '_section_type': 'yaml_body'},
                        )
                    )
                    chunk_index += 1
                current_doc = []
                current_size = 0

            current_doc.append(line)
            current_size += len(line) + 1

        if current_doc:
            chunk_text = '\n'.join(current_doc).strip()
            if chunk_text:
                chunks.append(
                    DocumentChunk(
                        id=f'{document_id}_chunk_{chunk_index}',
                        document_id=document_id,
                        chunk_index=chunk_index,
                        content=chunk_text,
                        metadata={**(metadata or {}), '_section_type': 'yaml_body'},
                    )
                )

        return (
            chunks
            if chunks
            else self.chunk_text_fallback(content, document_id, metadata)
        )

    def chunk_text_fallback(
        self, content: str, document_id: str, metadata: dict[str, Any] | None
    ) -> list[DocumentChunk]:
        """Basic sliding window for text files."""
        chunks: list[DocumentChunk] = []
        max_size, overlap = self.get_chunk_params('.txt')
        start = 0
        chunk_index = 0

        while start < len(content):
            end = start + max_size
            chunk_text = content[start:end]
            chunks.append(
                DocumentChunk(
                    id=f'{document_id}_chunk_{chunk_index}',
                    document_id=document_id,
                    chunk_index=chunk_index,
                    content=chunk_text.strip(),
                    metadata={**(metadata or {}), '_section_type': 'text'},
                )
            )
            chunk_index += 1
            start = end - overlap if end < len(content) else len(content)

        return chunks
