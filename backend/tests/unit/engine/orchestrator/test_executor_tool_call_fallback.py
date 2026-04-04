from __future__ import annotations

from types import SimpleNamespace


class _Safety:
    def apply(self, response_text, actions):
        return True, actions


class _LLMStub:
    def __init__(self, response_content: str):
        self._response_content = response_content
        self.last_kwargs: dict | None = None

        # Provide a minimal features object
        self.features = SimpleNamespace(supports_stop_words=True)

    def is_function_calling_active(self) -> bool:
        return False

    def completion(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            id='r1',
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=self._response_content))
            ],
        )
