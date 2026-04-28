r"""Detect and repair literal-escape residue in LLM-authored file content.

Problem this solves
-------------------
LLMs sometimes double-escape string content when emitting OpenAI-style tool
calls, e.g. producing ``"new_str": "<div class=\\\"foo\\\">\\n  hi"`` on the
wire. After a strict ``json.loads``, the Python string we hand to the file
editor is::

    <div class=\"foo\">\n  hi

(two-character sequences ``\\` + `"`` and ``\\` + `n``). If we write that
verbatim to ``index.html`` the browser gets invalid markup and tree-sitter
rejects it.

Claude Code sidesteps this entirely by using Anthropic's native ``tool_use``
where ``input`` arrives as a structured object (no inner JSON string for the
model to mis-escape). For the OpenAI-compatible path we have to detect and
repair.

Policy
------
Split by file type so we never corrupt legitimate code:

* **Strict markup** (HTML/CSS/SVG/XML/YAML/TOML/...): a single literal
  escape pair is already a grammar error, so repair on sight.
* **Heuristic code** (JS/TS/Python/JSON/...): ``"\\n"`` can legally appear
  inside string literals, so only repair when the residue count dominates
  real newlines (the whole blob was over-escaped, not a handful of quoted
  ``\\n`` inside a string constant).

The repair is a narrow unicode-style decode that handles the five escape
sequences models actually get wrong in practice (``\\n``, ``\\t``, ``\\r``,
``\\"``, ``\\'``) and passes everything else through unchanged. We
deliberately do **not** call ``codecs.decode(..., 'unicode_escape')`` because
that also mangles legitimate single-backslash content (Windows paths, regex
patterns, LaTeX).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# Markup / data files where literal ``\n`` / ``\"`` / ``\t`` pairs are NEVER
# legal source text. For these we always repair on sight (no ratio check) —
# any residue at all means the model double-escaped.
_STRICT_MARKUP_EXTS: frozenset[str] = frozenset(
    {
        '.html',
        '.htm',
        '.xhtml',
        '.svg',
        '.xml',
        '.css',
        '.scss',
        '.sass',
        '.less',
        '.yaml',
        '.yml',
        '.toml',
    }
)

# Code / data files where ``"\n"`` can legitimately appear inside source-level
# string literals (e.g. ``print("hi\n")`` in Python, JSON string escapes).
# We still repair, but only when residue vastly outnumbers real newlines
# (strong evidence the *whole blob* was over-escaped, not a handful of
# legitimate ``\n`` literals inside string constants).
_HEURISTIC_CODE_EXTS: frozenset[str] = frozenset(
    {
        '.js',
        '.jsx',
        '.mjs',
        '.cjs',
        '.ts',
        '.tsx',
        '.json',
        '.jsonc',
        '.py',
        '.pyi',
        '.go',
        '.rs',
        '.java',
        '.kt',
        '.swift',
        '.c',
        '.h',
        '.cc',
        '.cpp',
        '.hpp',
        '.cs',
        '.rb',
        '.php',
        '.sh',
        '.bash',
        # Markdown: ``\n`` / ``\"`` pairs in prose are a bug 99% of the time,
        # but the heuristic gate keeps us safe on the 1% where they're in a
        # fenced code block. Included so models that double-escape markdown
        # writes don't leave literal ``\n`` sprinkled through headings.
        '.md',
        '.markdown',
    }
)

_STRUCTURED_TEXT_EXTS: frozenset[str] = _STRICT_MARKUP_EXTS | _HEURISTIC_CODE_EXTS


@dataclass(frozen=True)
class RepairReport:
    """Outcome of ``repair_literal_escapes``."""

    content: str
    changed: bool
    replacements: int
    reason: str  # 'not_applicable' | 'no_residue' | 'repaired'

    @property
    def should_warn(self) -> bool:
        return self.changed


def _ext(path: str | os.PathLike[str] | None) -> str:
    if not path:
        return ''
    try:
        return Path(os.fspath(path)).suffix.lower()
    except (TypeError, ValueError):
        return ''


def _is_structured_text_path(path: str | os.PathLike[str] | None) -> bool:
    return _ext(path) in _STRUCTURED_TEXT_EXTS


def _is_strict_markup_path(path: str | os.PathLike[str] | None) -> bool:
    """True for markup/data files where any literal escape residue is invalid."""
    return _ext(path) in _STRICT_MARKUP_EXTS


# Matches ``\n`` / ``\t`` / ``\r`` / ``\"`` / ``\'`` **that appear as two
# characters** (a literal backslash followed by n/t/r/quote) but are NOT part
# of a longer escape sequence like ``\\n`` (which the model intentionally
# typed as an escaped backslash plus an ``n``).
#
# A negative lookbehind ``(?<!\\)`` excludes any preceding backslash so we
# only match odd-parity backslashes. This is the same heuristic used by
# most JSON "repair" libraries for this class of error.
_LITERAL_ESCAPE_RE = re.compile(r'(?<!\\)\\([ntr"\'])')

# Matches ``\\n`` / ``\\t`` / ``\\r`` / ``\\"`` / ``\\'`` — two literal
# backslashes followed by the escape character. Only applied to strict-markup
# files where such a sequence is never valid source text. This catches the
# output of models that over-escape twice (tool JSON -> Python string -> disk
# bytes end up as ``\\n``), which the odd-parity regex above deliberately
# leaves alone to protect legitimate ``\\n`` in code.
_STRICT_DOUBLE_ESCAPE_RE = re.compile(r'\\\\([ntr"\'])')


def _strict_markup_has_residue(content: str, residue_count: int) -> bool:
    if residue_count > 0:
        return True
    return bool(_STRICT_DOUBLE_ESCAPE_RE.search(content))


def _heuristic_code_has_residue(content: str, residue_count: int) -> bool:
    if residue_count < 2:
        return False

    real_newlines = content.count('\n')
    if real_newlines == 0:
        return True

    literal_newlines = content.count('\\n')
    if literal_newlines >= real_newlines:
        return True
    return literal_newlines == 0 and residue_count >= 4 and real_newlines < 2


def _repair_argument_field(
    arguments: dict[str, object],
    field_name: str,
    path: str | os.PathLike[str] | None,
    changes: list[tuple[str, int]],
    *,
    record_name: str | None = None,
) -> None:
    value = arguments.get(field_name)
    if not isinstance(value, str) or not value:
        return

    report = repair_literal_escapes(value, path)
    if not report.changed:
        return

    arguments[field_name] = report.content
    changes.append(((record_name or field_name), report.replacements))


def _repair_batch_argument_entries(
    arguments: dict[str, object],
    batch_key: str,
    path: str | os.PathLike[str] | None,
    changes: list[tuple[str, int]],
) -> None:
    batch = arguments.get(batch_key)
    if not isinstance(batch, list):
        return

    for index, item in enumerate(batch):
        if not isinstance(item, dict):
            continue
        _repair_argument_field(
            item,
            'new_body',
            path,
            changes,
            record_name=f'{batch_key}[{index}].new_body',
        )


def has_literal_escape_residue(
    content: str, path: str | os.PathLike[str] | None
) -> bool:
    r"""Return True when ``content`` looks like it came out of a double-escape.

    Two policies depending on file type:

    * **Strict markup** (HTML/CSS/SVG/XML/YAML/TOML/...): any literal escape
      pair at all is illegal source text → repair aggressively. A single
      ``\\"`` or ``\\n`` is enough evidence. Double-backslash variants
      (``\\\\n``) are also treated as residue for these files.

    * **Heuristic code** (JS/TS/Python/JSON/...): ``"\\n"`` is legitimate
      *inside* string literals, so we only repair when residue vastly
      outnumbers real newlines (the whole blob was over-escaped). We also
      count all residue kinds, not just ``\\n``, so HTML-style double
      quotes in JSX still trigger repair when the file has no real newlines.
    """
    if not isinstance(content, str) or not content:
        return False
    if not _is_structured_text_path(path):
        return False

    residue_count = len(_LITERAL_ESCAPE_RE.findall(content))

    if _is_strict_markup_path(path):
        return _strict_markup_has_residue(content, residue_count)

    if residue_count == 0:
        return False
    return _heuristic_code_has_residue(content, residue_count)


def repair_literal_escapes(
    content: str, path: str | os.PathLike[str] | None
) -> RepairReport:
    r"""Repair over-escaped content when residue is detected.

    Returns a ``RepairReport`` describing what happened. The ``content`` field
    always holds the version to write to disk — equal to the input when no
    repair was applied.

    For strict-markup files (HTML/CSS/SVG/XML/YAML/TOML/markdown-adjacent)
    we additionally collapse ``\\\\n`` / ``\\\\t`` / ``\\\\r`` / ``\\\\"`` /
    ``\\\\'`` — two literal backslashes followed by the escape char. Models
    that over-escape twice produce exactly this pattern (seen in Kimi K2.5
    output against NVIDIA's OpenAI-compatible endpoint), and no HTML/CSS
    grammar accepts ``\\n`` as source text.
    """
    if not _is_structured_text_path(path):
        return RepairReport(content, False, 0, 'not_applicable')
    if not has_literal_escape_residue(content, path):
        return RepairReport(content, False, 0, 'no_residue')

    count = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        ch = match.group(1)
        if ch == 'n':
            return '\n'
        if ch == 't':
            return '\t'
        if ch == 'r':
            return '\r'
        return ch  # '"' or "'" — drop the leading backslash

    repaired = _LITERAL_ESCAPE_RE.sub(_sub, content)

    # Strict markup files: also collapse double-backslash variants. Order
    # matters — the single-backslash pass above runs first so ``\n`` becomes
    # a real newline before this pass rewrites ``\\n`` → ``\n``. Without
    # this, a mixed blob (``\\n`` in one place, ``\n`` in another) would
    # convert inconsistently.
    if _is_strict_markup_path(path):
        repaired = _STRICT_DOUBLE_ESCAPE_RE.sub(_sub, repaired)

    if repaired == content:
        return RepairReport(content, False, 0, 'no_residue')
    return RepairReport(repaired, True, count, 'repaired')


# Fields on a file-editor tool call whose value is "file content" and should
# be scanned for escape residue before being handed off to disk.
CONTENT_ARG_NAMES: tuple[str, ...] = (
    'file_text',
    'new_str',
    'new_body',
    'content',
    'new_code',
    'section_content',
    'patch_text',
)


def repair_arguments_in_place(
    arguments: object, path: str | os.PathLike[str] | None
) -> list[tuple[str, int]]:
    """Repair any content-bearing string field of ``arguments`` in place.

    Returns a list of ``(field_name, replacements)`` pairs for every field
    that was actually rewritten; an empty list means nothing changed.
    """
    if not isinstance(arguments, dict):
        return []
    changes: list[tuple[str, int]] = []
    for name in CONTENT_ARG_NAMES:
        _repair_argument_field(arguments, name, path, changes)
    for batch_key in ('edits', 'symbol_edits'):
        _repair_batch_argument_entries(arguments, batch_key, path, changes)
    return changes
