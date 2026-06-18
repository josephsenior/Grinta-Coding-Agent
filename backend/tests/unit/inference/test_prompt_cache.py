from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.inference.caching import prompt_cache


def test_get_prompt_cache_returns_noop_for_missing_provider() -> None:
    backend = prompt_cache.get_prompt_cache(None)
    handle = backend.get_or_create_cache_handle(
        client=None,
        model='m',
        system_instruction=None,
        messages=[],
    )
    assert handle is None


def test_register_prompt_cache_backend_and_fetch() -> None:
    class _Backend:
        def get_or_create_cache_handle(
            self, *, client, model: str, system_instruction: str | None, messages
        ) -> str | None:
            return f'{model}-cache'

    key = 'custom-provider'
    old = dict(prompt_cache._REGISTRY)
    try:
        prompt_cache.register_prompt_cache_backend(key, _Backend())
        backend = prompt_cache.get_prompt_cache('CUSTOM-provider')
        assert (
            backend.get_or_create_cache_handle(
                client=None,
                model='abc',
                system_instruction='sys',
                messages=[],
            )
            == 'abc-cache'
        )
    finally:
        prompt_cache._REGISTRY.clear()
        prompt_cache._REGISTRY.update(old)


def test_get_prompt_cache_unknown_provider_returns_noop() -> None:
    backend = prompt_cache.get_prompt_cache('unknown-provider')
    result = backend.get_or_create_cache_handle(
        client=object(),
        model='x',
        system_instruction='s',
        messages=[{'role': 'user', 'content': 'hello'}],
    )
    assert result is None


def test_register_default_backends_with_gemini_adapter() -> None:
    fake_manager = MagicMock()
    fake_manager.get_or_create_cache.return_value = 'gem-handle'
    old = dict(prompt_cache._REGISTRY)
    try:
        prompt_cache._REGISTRY.clear()
        with patch('backend.inference.caching.gemini_cache.gemini_cache_manager', fake_manager):
            prompt_cache._register_default_backends()
        backend = prompt_cache.get_prompt_cache('google')
        out = backend.get_or_create_cache_handle(
            client='c',
            model='m',
            system_instruction='sys',
            messages=[{'role': 'user', 'content': 'x'}],
        )
        assert out == 'gem-handle'
        fake_manager.get_or_create_cache.assert_called_once()
    finally:
        prompt_cache._REGISTRY.clear()
        prompt_cache._REGISTRY.update(old)


def test_register_default_backends_fallback_when_module_missing() -> None:
    old = dict(prompt_cache._REGISTRY)
    try:
        prompt_cache._REGISTRY.clear()
        with patch.dict('sys.modules', {'backend.inference.caching.gemini_cache': None}):
            prompt_cache._register_default_backends()
        assert (
            prompt_cache.get_prompt_cache('google').get_or_create_cache_handle(
                client=None, model='m', system_instruction=None, messages=[]
            )
            is None
        )
    finally:
        prompt_cache._REGISTRY.clear()
        prompt_cache._REGISTRY.update(old)
