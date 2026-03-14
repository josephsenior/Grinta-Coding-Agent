from typing import Any
from backend.core.message import Message

def _flatten_content_list(content_val: list[Any]) -> str:
    texts = [
        str(item["text"])
        for item in content_val
        if isinstance(item, dict) and "text" in item
    ]
    return "\n".join(texts)

def _extract_text_chunks(msg: Message) -> list[str]:
    fallback_lines: list[str] = []
    for chunk in getattr(msg, "content", []) or []:
        value = getattr(chunk, "text", None)
        if value is None and isinstance(chunk, dict):
            value = chunk.get("text")
        if value:
            fallback_lines.append(str(value))
    return fallback_lines

def _serialize_message_with_fallback(msg: Message) -> dict:
    try:
        return msg.serialize_model()  # type: ignore[attr-defined]
    except Exception:
        fallback_lines = _extract_text_chunks(msg)
        return {
            "role": msg.role,
            "content": "\n".join(fallback_lines),
        }

def _serialize_single_message(msg: Message) -> dict:
    raw = _serialize_message_with_fallback(msg)
    content_val = raw.get("content", "")
    if isinstance(content_val, list):
        raw["content"] = _flatten_content_list(content_val)
    return raw

def serialize_messages(messages: list[Message]) -> list[dict]:
    serialized: list[dict] = []
    for msg in messages:
        serialized.append(_serialize_single_message(msg))
    return serialized
