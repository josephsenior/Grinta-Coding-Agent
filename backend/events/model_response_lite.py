from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class AssistantToolCallLite(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str | None = None
    # Optional extra payload for debugging; not relied on by core logic
    function: Any | None = None


class AssistantMessageLite(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    role: str | None = None
    content: Any = None
    tool_calls: list[AssistantToolCallLite] | None = None


class ChoiceLite(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    message: AssistantMessageLite | None = None


class ModelResponseLite(BaseModel):
    """A minimal, stable subset of a chat completion response used in metadata.

    Designed to be serializable and resilient to upstream SDK changes while
    preserving only what downstream code needs (id, choices[0].message.content,
    message.tool_calls[*].id, etc.).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str | None = None
    model: str | None = None
    choices: list[ChoiceLite] = []

    @staticmethod
    def _getattr_or_get(obj: Any, name: str, default: Any = None) -> Any:
        if hasattr(obj, name):
            return getattr(obj, name)
        if isinstance(obj, dict):
            return obj.get(name, default)
        return default

    @classmethod
    def from_sdk(cls, resp: Any) -> ModelResponseLite:
        rid = cls._getattr_or_get(resp, "id")
        rmodel = cls._getattr_or_get(resp, "model")
        raw_choices = cls._getattr_or_get(resp, "choices", []) or []
        choices: list[ChoiceLite] = []
        for ch in raw_choices:
            raw_msg = cls._getattr_or_get(ch, "message")
            if raw_msg is None:
                choices.append(ChoiceLite(message=None))
                continue
            role = cls._getattr_or_get(raw_msg, "role")
            content = cls._getattr_or_get(raw_msg, "content")
            raw_tool_calls = cls._getattr_or_get(raw_msg, "tool_calls")
            tool_calls: list[AssistantToolCallLite] | None = None
            if isinstance(raw_tool_calls, list):
                tool_calls = []
                for tc in raw_tool_calls:
                    tc_id = cls._getattr_or_get(tc, "id")
                    function = cls._getattr_or_get(tc, "function")
                    tool_calls.append(
                        AssistantToolCallLite(id=tc_id, function=function)
                    )
            msg = AssistantMessageLite(
                role=role, content=content, tool_calls=tool_calls
            )
            choices.append(ChoiceLite(message=msg))
        return cls(id=rid, model=rmodel, choices=choices)

    # Provide dict-like get for convenience in helper utilities
    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)
