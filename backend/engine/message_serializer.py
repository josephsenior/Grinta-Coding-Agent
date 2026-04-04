import os
from typing import Any

from backend.core.logger import app_logger as logger
from backend.core.message import Message


class MessageSerializationError(RuntimeError):
    """Raised when a message cannot be serialized without losing structured fields."""


def _flatten_content_list(content_val: list[Any]) -> str:
    texts = [
        str(item['text'])
        for item in content_val
        if isinstance(item, dict) and 'text' in item
    ]
    return '\n'.join(texts)


def _extract_text_chunks(msg: Message) -> list[str]:
    fallback_lines: list[str] = []
    for chunk in getattr(msg, 'content', []) or []:
        value = getattr(chunk, 'text', None)
        if value is None and isinstance(chunk, dict):
            value = chunk.get('text')
        if value:
            fallback_lines.append(str(value))
    return fallback_lines


def _serialize_message_with_fallback(msg: Message) -> dict:
    try:
        return msg.serialize_model()  # type: ignore[attr-defined]
    except Exception as e:
        logger.error(
            'Structured message serialization failed for role=%s: %s',
            getattr(msg, 'role', '?'),
            e,
            exc_info=True,
        )
        degraded = os.getenv(
            'APP_DEGRADED_MESSAGE_SERIALIZATION', ''
        ).strip().lower() in (
            '1',
            'true',
            'yes',
        )
        if degraded:
            logger.warning(
                'APP_DEGRADED_MESSAGE_SERIALIZATION is enabled — emitting flattened text-only message'
            )
            fallback_lines = _extract_text_chunks(msg)
            return {
                'role': msg.role,
                'content': '\n'.join(fallback_lines),
            }
        raise MessageSerializationError(
            'Message serialization failed; enable APP_DEGRADED_MESSAGE_SERIALIZATION=1 '
            'to allow a logged text-only fallback.'
        ) from e


def _serialize_single_message(msg: Message) -> dict:
    raw = _serialize_message_with_fallback(msg)
    content_val = raw.get('content', '')
    if isinstance(content_val, list):
        raw['content'] = _flatten_content_list(content_val)
    return raw


def serialize_messages(messages: list[Message]) -> list[dict]:
    serialized: list[dict] = []
    for msg in messages:
        serialized.append(_serialize_single_message(msg))
    return serialized
