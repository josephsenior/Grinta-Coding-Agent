"""Optional structured fields embedded in the first user message.

Clients may prefix the task with a single-line JSON object so validators can
avoid guessing from prose.

Format (first line only)::

    APP_TASK_JSON:{"expected_output_files":["out.txt","report.md"]}

Everything after the first newline is the human-readable ``Task.description``.
If the prefix is missing or JSON is invalid, the full string is treated as
description and no structured fields apply.

Benchmark-style prompts may also include a ``VALIDATION`` section between
banner lines; ``extract_task_rubric`` parses numbered and bulleted gates from
that section when structured JSON is not provided.
"""

from __future__ import annotations

import json
import re
from typing import Any

APP_TASK_JSON_PREFIX = 'APP_TASK_JSON:'

_SECTION_RE = re.compile(
    r'^={5,}\s*\n([^\n=]+?)\s*\n={5,}\s*\n(.*?)(?=^={5,}\s*\n|\Z)',
    re.MULTILINE | re.DOTALL,
)
_NUMBERED_ITEM_RE = re.compile(r'^\s*\d+\.\s+(.+?)\s*$')
_BULLET_ITEM_RE = re.compile(r'^\s*[-*]\s+(.+?)\s*$')


def parse_task_from_user_message(content: str) -> tuple[str, dict[str, Any]]:
    """Split user message into description and optional structured metadata.

    Returns:
        ``(description, meta_dict)``. ``meta_dict`` is empty when unset.
    """
    if not content:
        return '', {}

    stripped = content.lstrip('\ufeff')
    if not stripped.startswith(APP_TASK_JSON_PREFIX):
        return content, {}

    rest = stripped[len(APP_TASK_JSON_PREFIX) :]
    newline = rest.find('\n')
    if newline == -1:
        json_line, body = rest, ''
    else:
        json_line, body = rest[:newline], rest[newline + 1 :]

    json_line = json_line.strip()
    if not json_line:
        return body if body else content, {}

    try:
        meta = json.loads(json_line)
    except json.JSONDecodeError:
        return content, {}

    if not isinstance(meta, dict):
        return content, {}

    return (body if body else '').strip() or content, meta


def _section_text(description: str, title: str) -> str | None:
    target = title.strip().lower()
    for section_title, body in _SECTION_RE.findall(description):
        if section_title.strip().lower() == target:
            return body
    return None


def _extract_numbered_items(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        match = _NUMBERED_ITEM_RE.match(line)
        if match:
            item = match.group(1).strip()
            if item:
                items.append(item)
    return items


def _extract_bullets_after_marker(text: str, marker: str) -> list[str]:
    lowered = text.lower()
    marker_lower = marker.lower()
    idx = lowered.find(marker_lower)
    if idx < 0:
        return []

    rest = text[idx + len(marker) :]
    items: list[str] = []
    started = False
    for line in rest.splitlines():
        stripped = line.strip()
        if not stripped:
            if started:
                break
            continue
        bullet = _BULLET_ITEM_RE.match(line)
        numbered = _NUMBERED_ITEM_RE.match(line)
        if bullet:
            started = True
            items.append(bullet.group(1).strip())
            continue
        if numbered:
            started = True
            items.append(numbered.group(1).strip())
            continue
        if started:
            break
    return items


def extract_task_rubric(description: str) -> tuple[list[str], list[str]]:
    """Extract requirements and acceptance criteria from benchmark prose.

    Looks for a ``VALIDATION`` banner section and collects:
    - numbered checklist items as acceptance criteria
    - bullets under ``Do not claim full success unless`` as acceptance criteria
    """
    validation = _section_text(description, 'VALIDATION')
    if not validation:
        return [], []

    acceptance: list[str] = []
    acceptance.extend(_extract_numbered_items(validation))
    acceptance.extend(
        _extract_bullets_after_marker(
            validation,
            'Do not claim full success unless',
        )
    )
    acceptance.extend(
        _extract_bullets_after_marker(
            validation,
            'Final report must include',
        )
    )

    deduped: list[str] = []
    seen: set[str] = set()
    for item in acceptance:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return [], deduped


def _string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    items = [str(item).strip() for item in value if str(item).strip()]
    return items


def merge_task_fields(
    description: str,
    meta: dict[str, Any],
) -> tuple[str, list[str], list[str], list[str] | None]:
    """Build task fields from structured metadata and optional prose rubric."""
    requirements, acceptance = extract_task_rubric(description)

    meta_requirements = _string_list(meta.get('requirements'))
    if meta_requirements is not None:
        requirements = meta_requirements

    meta_acceptance = _string_list(meta.get('acceptance_criteria'))
    if meta_acceptance is not None:
        acceptance = meta_acceptance

    expected_files: list[str] | None = None
    raw_expected = meta.get('expected_output_files')
    if isinstance(raw_expected, list) and all(isinstance(x, str) for x in raw_expected):
        expected_files = list(raw_expected)

    return description, requirements, acceptance, expected_files
