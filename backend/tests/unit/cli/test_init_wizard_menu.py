from __future__ import annotations

from backend.cli.onboarding.init_wizard import (
    _build_all_provider_items,
    _build_detected_provider_items,
    _model_options_for_provider,
)
from backend.cli.onboarding.menu_prompts import (
    format_detected_model_preview,
    prompt_numbered_choice,
)


def test_format_detected_model_preview() -> None:
    assert format_detected_model_preview([]) == 'running (no models listed)'
    assert format_detected_model_preview(['a', 'b']) == 'a, b'
    assert (
        format_detected_model_preview(['a', 'b', 'c', 'd', 'e'])
        == 'a, b, c, d (+1 more)'
    )


def test_build_detected_provider_items() -> None:
    items = _build_detected_provider_items(
        ['ollama'],
        {'ollama': ['llama3.2', 'phi3']},
    )
    assert len(items) == 1
    assert items[0][0] == 'ollama'
    assert 'llama3.2' in items[0][1]


def test_build_all_provider_items_includes_openai() -> None:
    keys = [key for key, _label in _build_all_provider_items()]
    assert 'openai' in keys


def test_model_options_prefers_discovered_local_models() -> None:
    options = _model_options_for_provider('ollama', {'ollama': ['llama3.2']})
    assert options == ['llama3.2']


def test_prompt_numbered_choice_returns_selection(monkeypatch) -> None:
    from rich.console import Console

    from backend.cli.onboarding import menu_prompts as mp

    monkeypatch.setattr(mp.Prompt, 'ask', lambda *a, **k: '2')
    console = Console(no_color=True, force_terminal=False, width=80)
    result = prompt_numbered_choice(
        console,
        title='Pick one:',
        items=[('a', 'Alpha'), ('b', 'Beta')],
    )
    assert result == 'b'
