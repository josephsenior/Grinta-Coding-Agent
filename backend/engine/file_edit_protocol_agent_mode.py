"""Strict agent-mode raw edit block parsing and validation protocol."""

from __future__ import annotations

import json
from typing import Any

class AgentModeProtocolError(ValueError):
    """Raised when LLM output violates the strict agent-mode protocol."""

    def __init__(self, message: str, error_details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_details = error_details or {}

    def to_formatted_message(self) -> str:
        if self.error_details:
            return json.dumps(self.error_details, indent=2)
        return self.args[0]


def parse_raw_edit_block(text: str, delimiter_token: str) -> dict[str, Any]:
    """Parse the raw edit block formatted by the model.

    Enforces that:
    - Text must start with EDIT_FILE (ignoring whitespace).
    - No leading prose, no trailing prose.
    - Demarcated by RAW_LINES <token> and END_RAW_LINES <token>.
    - Extract and return headers and raw lines content.
    """
    cleaned = text.strip()
    if not cleaned.startswith("EDIT_FILE"):
        raise AgentModeProtocolError("Response must start with EDIT_FILE.")

    raw_lines_marker = f"RAW_LINES {delimiter_token}"
    end_raw_lines_marker = f"END_RAW_LINES {delimiter_token}"

    # Find the true start of RAW_LINES (not preceded by END_)
    start_search_idx = 0
    true_raw_lines_idx = -1
    while True:
        idx = cleaned.find(raw_lines_marker, start_search_idx)
        if idx == -1:
            break
        if idx >= 4 and cleaned[idx-4:idx] == "END_":
            start_search_idx = idx + len(raw_lines_marker)
            continue
        true_raw_lines_idx = idx
        break

    if true_raw_lines_idx == -1:
        raise AgentModeProtocolError(f"Missing {raw_lines_marker} marker in response.")
    if end_raw_lines_marker not in cleaned:
        raise AgentModeProtocolError(f"Missing {end_raw_lines_marker} marker in response.")

    headers_part = cleaned[:true_raw_lines_idx].strip()
    content_part = cleaned[true_raw_lines_idx + len(raw_lines_marker):]

    header_lines = headers_part.splitlines()
    if not header_lines or header_lines[0].strip() != "EDIT_FILE":
        raise AgentModeProtocolError("Block header must begin with EDIT_FILE.")

    headers: dict[str, str] = {}
    for line in header_lines[1:]:
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            raise AgentModeProtocolError(f"Malformed header line (missing colon): '{line}'")
        key, val = line.split(":", 1)
        headers[key.strip().lower()] = val.strip()

    if "path" not in headers:
        raise AgentModeProtocolError("Required header 'path' is missing.")
    if "command" not in headers:
        raise AgentModeProtocolError("Required header 'command' is missing.")

    # Split on END_RAW_LINES marker
    content_parts = content_part.split(end_raw_lines_marker, 1)
    if len(content_parts) != 2:
        raise AgentModeProtocolError("Malformed raw lines demarcation.")

    raw_content = content_parts[0]
    trailing = content_parts[1].strip()
    if trailing:
        raise AgentModeProtocolError("Prose or text after the raw edit block is forbidden.")

    # Strip exactly one leading and one trailing newline if present, to preserve literal formatting
    if raw_content.startswith("\r\n"):
        raw_content = raw_content[2:]
    elif raw_content.startswith("\n"):
        raw_content = raw_content[1:]

    if raw_content.endswith("\r\n"):
        raw_content = raw_content[:-2]
    elif raw_content.endswith("\n"):
        raw_content = raw_content[:-1]

    return {
        "headers": headers,
        "content": raw_content
    }


def validate_edit_command_metadata(command: str, metadata: dict[str, Any]) -> str:
    """Validate edit command-specific metadata and return normalized operation name.

    Allowed operations: insert, replace_range, edit_symbol, edit_symbols, multi_edit
    """
    cmd_norm = command.strip().lower()

    # Normalization mapping (no aliases allowed, only exact names)
    op_map = {
        "insert": "insert",
        "replace_range": "replace_range",
        "edit_symbol": "edit_symbol",
        "edit_symbols": "edit_symbols",
        "multi_edit": "multi_edit",
    }

    op = op_map.get(cmd_norm)
    if not op:
        error_details = {
            "ok": False,
            "error_code": "UNKNOWN_EDIT_COMMAND",
            "message": "The requested edit command is not registered.",
            "known_commands": ["insert", "replace_range", "edit_symbol", "edit_symbols", "multi_edit"]
        }
        raise AgentModeProtocolError("Unknown edit command.", error_details)

    # Command-specific validation
    missing_fields = []
    if op == "insert":
        if "insert_line" not in metadata:
            missing_fields.append("insert_line")
        else:
            try:
                metadata["insert_line"] = int(metadata["insert_line"])
            except ValueError:
                raise AgentModeProtocolError("Field 'insert_line' must be an integer.")

    elif op == "replace_range":
        if "start_line" not in metadata:
            missing_fields.append("start_line")
        if "end_line" not in metadata:
            missing_fields.append("end_line")
        
        for field in ("start_line", "end_line"):
            if field in metadata:
                try:
                    metadata[field] = int(metadata[field])
                except ValueError:
                    raise AgentModeProtocolError(f"Field '{field}' must be an integer.")

    elif op == "edit_symbol":
        if "symbol_name" not in metadata:
            missing_fields.append("symbol_name")

    if missing_fields:
        error_details = {
            "ok": False,
            "error_code": "MISSING_COMMAND_FIELD",
            "message": "The selected command requires additional metadata.",
            "missing_fields": missing_fields
        }
        raise AgentModeProtocolError("Missing command field.", error_details)

    return op
