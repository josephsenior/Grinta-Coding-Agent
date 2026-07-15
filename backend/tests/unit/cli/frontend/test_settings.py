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


def test_settings_model_refresh_preserves_selection_made_while_loading() -> None:
    from types import SimpleNamespace

    from backend.cli.tui.dialogs.settings import GrintaSettingsDialog

    dialog = object.__new__(GrintaSettingsDialog)
    dialog._selected_model_value = 'new-model'
    dialog._entries_by_provider = {}
    controls = {
        '#settings-model': SimpleNamespace(value=None, set_options=lambda _: None),
        '#settings-custom-model': SimpleNamespace(value=''),
    }
    dialog.query_one = lambda selector, _type=None: controls[selector]
    dialog._model_options = lambda _provider: [('New model', 'new-model')]
    dialog._current_model_for_provider = lambda _provider: 'old-model'
    dialog._current_custom_model_for_provider = lambda _provider: ''
    dialog._sync_custom_model_visibility = lambda: None
    dialog._sync_reasoning_options = lambda *_args: None
    dialog._sync_model_metadata = lambda: None

    dialog._apply_model_list_to_ui('openai', preferred_model='new-model')

    assert controls['#settings-model'].value == 'new-model'
    assert dialog._selected_model_value == 'new-model'


def test_settings_submit_prefers_change_event_over_stale_select_value() -> None:
    from types import SimpleNamespace

    from backend.cli.tui.dialogs.settings import GrintaSettingsDialog

    dialog = object.__new__(GrintaSettingsDialog)
    dialog._selected_model_value = 'new-model'
    controls = {
        '#settings-model': SimpleNamespace(value='old-model', selection='old-model'),
        '#settings-custom-model': SimpleNamespace(value=''),
    }
    dialog.query_one = lambda selector, _type=None: controls[selector]
    dialog._selected_provider = lambda: 'openai'
    dialog._current_model_for_provider = lambda _provider: 'old-model'

    assert dialog._resolve_submit_model() == 'new-model'
