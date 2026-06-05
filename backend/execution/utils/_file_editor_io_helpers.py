"""Pure IO/encoding/message helpers for FileEditor.

No instance state — these helpers deal with byte/text round-tripping,
disk-payload encoding, write-success messages, and the ``_FileReadMeta``
dataclass that captures per-file encoding/newline metadata.

Extracted from ``backend.execution.utils._file_editor_ops_mixin`` to
keep that module focused on the ops mixin class.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class _FileReadMeta:
    """Encoding and newline style for round-tripping disk I/O."""

    encoding: str
    newline: Literal['crlf', 'lf']
    had_bom: bool


_QUOTE_TRANSLATE = str.maketrans(
    {
        '\u201c': '"',
        '\u201d': '"',
        '\u2018': "'",
        '\u2019': "'",
    }
)


def normalize_quotes(s: str) -> str:
    """Map typographic quotes to straight quotes (Claude Code normalizeQuotes)."""
    return s.translate(_QUOTE_TRANSLATE)


def _compose_create_file_success_message(content: str) -> str:
    preview_lines = content.splitlines()[:20]
    preview_str = '\n'.join(f'{i + 1}\t{line}' for i, line in enumerate(preview_lines))
    if len(content.splitlines()) > 20:
        preview_str += '\n...\n(File truncated)'
    line_end_desc = '\\r\\n' if '\r\n' in content else '\\n'
    return (
        'File created successfully. '
        f'Line endings: {line_end_desc}. File preview:\n{preview_str}'
    )


def _compose_write_success_message(
    *,
    is_create: bool,
    content: str,
    soft_warning: str,
) -> str:
    if is_create:
        output_msg = _compose_create_file_success_message(content)
    else:
        output_msg = 'File written successfully'
    if soft_warning:
        output_msg = f'{output_msg}\n{soft_warning}'
    return output_msg


def _normalize_newlines_for_metadata(content: str, meta: _FileReadMeta) -> str:
    if meta.newline == 'crlf':
        content = content.replace('\r\n', '\n')
        content = content.replace('\r', '')
        return content.replace('\n', '\r\n')
    return content


def _encode_disk_payload(content: str, meta: _FileReadMeta) -> bytes:
    if meta.encoding == 'utf-16-le':
        return b'\xff\xfe' + content.encode('utf-16-le')
    if meta.encoding == 'utf-16-be':
        return b'\xfe\xff' + content.encode('utf-16-be')
    if meta.encoding == 'utf-8-sig' or (meta.had_bom and meta.encoding == 'utf-8'):
        return b'\xef\xbb\xbf' + content.encode('utf-8')
    if meta.encoding == 'latin-1':
        return content.encode('latin-1')
    return content.encode('utf-8')


_LARGE_EXISTING_CODE_FILE_LINES = 200
_CODE_FILE_SUFFIXES: frozenset[str] = frozenset(
    {
        '.py',
        '.js',
        '.jsx',
        '.ts',
        '.tsx',
        '.go',
        '.rs',
        '.java',
        '.c',
        '.cpp',
        '.cc',
        '.cxx',
        '.h',
        '.hpp',
        '.cs',
        '.rb',
        '.php',
        '.swift',
        '.kt',
        '.scala',
    }
)


def _is_large_existing_code_file(file_path: Path, content: str | None) -> bool:
    if content is None or file_path.suffix.lower() not in _CODE_FILE_SUFFIXES:
        return False
    return len(content.splitlines()) >= _LARGE_EXISTING_CODE_FILE_LINES
