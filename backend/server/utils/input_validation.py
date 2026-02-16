"""Input validation and sanitization utilities.

Provides security-focused validation for:
- File paths (prevent directory traversal)
- Commands (prevent injection)
- API parameters
- File uploads
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote

from backend.core.logger import FORGE_logger as logger


class ValidationError(Exception):
    """Raised when input validation fails."""



def validate_file_path(path: str, base_dir: str | None = None) -> str:
    """Validate and sanitize a file path to prevent directory traversal.

    Args:
        path: File path to validate
        base_dir: Base directory to restrict paths to (optional)

    Returns:
        Normalized, validated path

    Raises:
        ValidationError: If path is invalid or contains traversal attempts
    """
    # Decode URL encoding
    path = unquote(path)

    # Remove null bytes
    if "\x00" in path:
        raise ValidationError("Path contains null bytes")

    # Normalize path
    normalized = os.path.normpath(path)

    # Check for directory traversal attempts
    if ".." in normalized or normalized.startswith("/"):
        if base_dir:
            # Resolve relative to base directory
            try:
                full_path = os.path.abspath(os.path.join(base_dir, normalized))
                base_abs = os.path.abspath(base_dir)
                if not full_path.startswith(base_abs):
                    raise ValidationError(f"Path traversal detected: {path}")
                return os.path.relpath(full_path, base_abs)
            except (OSError, ValueError) as e:
                raise ValidationError(f"Invalid path: {path}") from e
        else:
            raise ValidationError(f"Path traversal detected: {path}")

    # Check for dangerous characters
    dangerous_chars = ["<", ">", "|", "&", ";", "`", "$", "(", ")", "\n", "\r"]
    if any(char in normalized for char in dangerous_chars):
        raise ValidationError(f"Path contains dangerous characters: {path}")

    return normalized


def validate_command(command: str, allowed_commands: list[str] | None = None) -> str:
    """Validate a command to prevent injection attacks.

    Args:
        command: Command string to validate
        allowed_commands: List of allowed command prefixes (optional)

    Returns:
        Validated command

    Raises:
        ValidationError: If command is invalid or potentially dangerous
    """
    # Remove leading/trailing whitespace
    command = command.strip()

    if not command:
        raise ValidationError("Empty command")

    # Check for command injection patterns
    dangerous_patterns = [
        r"[;&|`$]",  # Command separators
        r"<\(|>\(",  # Process substitution
        r"\$\(",  # Command substitution
        r"\{.*\}",  # Brace expansion (if not intended)
        r"\(.*\)",  # Subshell execution
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, command):
            raise ValidationError(
                f"Potentially dangerous command pattern detected: {command}"
            )

    # Check against allowed commands if provided
    if allowed_commands:
        command_base = command.split()[0] if command.split() else ""
        if command_base not in allowed_commands:
            raise ValidationError(f"Command not in allowed list: {command_base}")

    return command


def _validate_type(value: str, param_type: str) -> None:
    """Validate parameter type.

    Raises:
        ValidationError: If type validation fails
    """
    if param_type == "int":
        try:
            int(value)
        except ValueError as exc:
            raise ValidationError(f"Invalid integer: {value}") from exc
    elif param_type == "float":
        try:
            float(value)
        except ValueError as exc:
            raise ValidationError(f"Invalid float: {value}") from exc
    elif param_type == "email":
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_pattern, value):
            raise ValidationError(f"Invalid email: {value}")
    elif param_type == "url":
        url_pattern = r"^https?://[^\s/$.?#].[^\s]*$"
        if not re.match(url_pattern, value):
            raise ValidationError(f"Invalid URL: {value}")


def _validate_length(
    value: str, min_length: int | None, max_length: int | None
) -> None:
    """Validate parameter length.

    Raises:
        ValidationError: If length validation fails
    """
    if min_length is not None and len(value) < min_length:
        raise ValidationError(f"Value too short (min {min_length}): {value}")
    if max_length is not None and len(value) > max_length:
        raise ValidationError(f"Value too long (max {max_length}): {value}")


def validate_api_parameter(
    value: str,
    param_type: str = "string",
    min_length: int | None = None,
    max_length: int | None = None,
    pattern: str | None = None,
    required: bool = True,
) -> str:
    """Validate an API parameter.

    Args:
        value: Parameter value to validate
        param_type: Expected type (string, int, float, email, url)
        min_length: Minimum length (for strings)
        max_length: Maximum length (for strings)
        pattern: Regex pattern to match (optional)
        required: Whether parameter is required

    Returns:
        Validated value

    Raises:
        ValidationError: If validation fails
    """
    if not value and required:
        raise ValidationError("Required parameter is missing")

    if not value:
        return value

    # Type validation
    _validate_type(value, param_type)

    # Length validation
    _validate_length(value, min_length, max_length)

    # Pattern validation
    if pattern and not re.match(pattern, value):
        raise ValidationError(f"Value does not match required pattern: {value}")

    return value


def validate_file_upload(
    filename: str,
    content: bytes,
    max_size: int = 10 * 1024 * 1024,  # 10MB default
    allowed_extensions: list[str] | None = None,
    allowed_mime_types: list[str] | None = None,
) -> tuple[str, bytes]:
    """Validate a file upload.

    Args:
        filename: Original filename
        content: File content
        max_size: Maximum file size in bytes
        allowed_extensions: List of allowed file extensions (e.g., ['.txt', '.pdf'])
        allowed_mime_types: List of allowed MIME types (optional)

    Returns:
        Tuple of (validated_filename, content)

    Raises:
        ValidationError: If file is invalid
    """
    # Validate filename
    validated_filename = validate_file_path(filename)

    # Check file size
    if len(content) > max_size:
        raise ValidationError(
            f"File too large (max {max_size} bytes): {len(content)} bytes"
        )

    # Check extension
    if allowed_extensions:
        ext = Path(validated_filename).suffix.lower()
        if ext not in allowed_extensions:
            raise ValidationError(f"File extension not allowed: {ext}")

    # Check MIME type (basic check based on content)
    if allowed_mime_types:
        # Simple MIME type detection (can be enhanced)
        detected_mime = _detect_mime_type(content, validated_filename)
        if detected_mime not in allowed_mime_types:
            raise ValidationError(f"MIME type not allowed: {detected_mime}")

    return validated_filename, content


def _detect_mime_type(content: bytes, filename: str) -> str:
    """Detect MIME type from content and filename.

    Args:
        content: File content
        filename: Filename

    Returns:
        MIME type string
    """
    # Simple MIME type detection based on file signature
    if content.startswith(b"\x89PNG"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith(b"%PDF"):
        return "application/pdf"
    if content.startswith(b"PK\x03\x04"):
        return "application/zip"
    # Fallback to extension-based detection
    ext = Path(filename).suffix.lower()
    mime_map = {
        ".txt": "text/plain",
        ".json": "application/json",
        ".html": "text/html",
        ".css": "text/css",
        ".js": "application/javascript",
        ".py": "text/x-python",
    }
    return mime_map.get(ext, "application/octet-stream")


def sanitize_string(value: str, max_length: int | None = None) -> str:
    """Sanitize a string by removing dangerous characters.

    Args:
        value: String to sanitize
        max_length: Maximum length (truncate if longer)

    Returns:
        Sanitized string
    """
    # Remove null bytes
    value = value.replace("\x00", "")

    # Remove control characters (except newline and tab)
    value = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", value)

    # Truncate if too long
    if max_length and len(value) > max_length:
        value = value[:max_length]
        logger.warning("String truncated to %s characters", max_length)

    return value
