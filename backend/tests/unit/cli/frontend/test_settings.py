"""CLI frontend — settings."""

from backend.tests.unit.cli.frontend._shared import (
    MagicMock,
    _console_output,
    _make_console,
    patch,
)

def test_settings_ai_tab_shows_provider_and_model_separately() -> None:
    from backend.cli.settings.settings_tui import _render_ai_tab

    console = _make_console()
    llm_cfg = MagicMock()
    llm_cfg.model = 'openai/google/gemini-3-flash-preview'
    llm_cfg.api_key = None

    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg
    config.max_budget_per_task = None
    config.cli_tool_icons = False

    with patch(
        'backend.cli.settings.settings_tui.load_app_config', return_value=config
    ):
        _render_ai_tab(console)

    output = _console_output(console)
    assert 'Provider' in output
    assert 'google' in output
    assert 'Model' in output
    assert 'gemini-3-flash-preview' in output
    assert 'openai/google' not in output
