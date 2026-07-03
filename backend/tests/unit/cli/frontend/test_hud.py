"""CLI frontend — hud."""

from backend.tests.unit.cli.frontend._shared import (
    HUDBar,
    Metrics,
    ResponseLatency,
    TokenUsage,
)

def test_hud_shows_mcp_server_count_when_set() -> None:
    hud = HUDBar()
    assert 'M:?' in hud._format().plain
    hud.update_mcp_servers(3)
    assert 'M:3' in hud._format().plain
    n_skills = HUDBar.count_bundled_playbook_skills()
    assert f'S:{min(n_skills, 99)}' in hud._format().plain

def test_hud_shows_provider_and_model_combined() -> None:
    """HUD shows 'provider/model' combined to reduce visual clutter.

    Previously the bar rendered ``provider: google  •  model: X``; the extra
    labels were redundant visual weight since the provider is already
    implied by the prefix of the model slug.
    """
    hud = HUDBar()
    hud.update_model('openai/google/gemini-3-flash-preview')

    bar = hud._format().plain

    assert 'google/gemini-3-flash-preview' in bar
    # The redundant separate labels must be gone.
    assert 'provider:' not in bar
    assert 'model:' not in bar
    # The raw "openai/google/..." with the provider prefix still should not leak.
    assert 'openai/google/gemini-3-flash-preview' not in bar
    assert hud._format_compact().plain == bar

def test_hud_prefers_model_provider_over_client_prefix() -> None:
    hud = HUDBar()
    hud.update_model('openai/lightning-ai/kimi-k2.5')

    bar = hud._format().plain

    assert 'lightning-ai/kimi-k2.5' in bar
    assert 'openai/lightning-ai/kimi-k2.5' not in bar

def test_hud_uses_client_when_model_has_no_provider_prefix() -> None:
    hud = HUDBar()
    hud.update_model('openai/gpt-4o')

    bar = hud._format().plain

    assert 'openai/gpt-4o' in bar

def test_hud_singular_mcp_label() -> None:
    hud = HUDBar()
    hud.update_mcp_servers(1)
    assert 'M:1' in hud._format().plain

def test_hud_tracks_llm_call_count() -> None:
    """HUD should count the number of LLM calls from token_usages list."""
    hud = HUDBar()
    metrics = Metrics()
    metrics.accumulated_cost = 0.5
    metrics.token_usages = [
        TokenUsage(prompt_tokens=100, completion_tokens=50),
        TokenUsage(prompt_tokens=200, completion_tokens=80),
        TokenUsage(prompt_tokens=150, completion_tokens=60),
    ]
    hud.update_from_llm_metrics(metrics)
    assert hud.state.llm_calls == 3
    assert hud.state.cost_usd == 0.5

def test_hud_displays_accumulated_tokens_while_preserving_context_pressure() -> None:
    hud = HUDBar()
    metrics = Metrics()
    metrics.add_token_usage(
        prompt_tokens=100,
        completion_tokens=50,
        cache_read_tokens=0,
        cache_write_tokens=0,
        context_window=4096,
        response_id='resp-1',
    )
    metrics.add_token_usage(
        prompt_tokens=200,
        completion_tokens=80,
        cache_read_tokens=0,
        cache_write_tokens=0,
        context_window=8192,
        response_id='resp-2',
    )

    hud.update_from_llm_metrics(metrics)

    assert hud.state.total_tokens == 430
    assert hud.state.context_tokens == 200
    assert hud.state.context_limit == 8192

    rendered = hud._format().plain
    assert '430' in rendered
    assert '200/8.2K' in rendered or '430 · 200/8192' in rendered

def test_hud_context_pressure_does_not_drop_on_smaller_later_call() -> None:
    hud = HUDBar()
    metrics = Metrics()
    metrics.add_token_usage(
        prompt_tokens=2_000,
        completion_tokens=80,
        cache_read_tokens=0,
        cache_write_tokens=0,
        context_window=16_000,
        response_id='resp-1',
    )
    metrics.add_token_usage(
        prompt_tokens=1_200,
        completion_tokens=40,
        cache_read_tokens=0,
        cache_write_tokens=0,
        context_window=16_000,
        response_id='resp-2',
    )

    hud.update_from_llm_metrics(metrics)

    assert hud.state.total_tokens == 3_320
    assert hud.state.context_tokens == 2_000
    assert hud.state.context_limit == 16_000

def test_hud_context_pressure_prefers_full_request_tokens() -> None:
    hud = HUDBar()
    metrics = Metrics()
    metrics.add_token_usage(
        prompt_tokens=12_000,
        completion_tokens=200,
        cache_read_tokens=0,
        cache_write_tokens=0,
        context_window=200_000,
        response_id='resp-1',
        full_request_tokens=18_500,
        usable_input_tokens=120_000,
    )

    hud.update_from_llm_metrics(metrics)

    assert hud.state.context_tokens == 18_500
    assert hud.state.context_limit == 120_000

def test_hud_apply_prompt_token_accounting_overlays_internal_estimate() -> None:
    hud = HUDBar()
    metrics = Metrics()
    metrics.add_token_usage(
        prompt_tokens=40_000,
        completion_tokens=100,
        cache_read_tokens=0,
        cache_write_tokens=0,
        context_window=200_000,
        response_id='resp-1',
    )
    hud.update_from_llm_metrics(metrics)
    assert hud.state.context_tokens == 40_000

    hud.apply_prompt_token_accounting(
        {
            'full_request_tokens': 52_000,
            'usable_input_tokens': 128_000,
        }
    )

    assert hud.state.context_tokens == 52_000
    assert hud.state.context_limit == 128_000

def test_hud_context_pressure_resets_after_condensation_epoch() -> None:
    hud = HUDBar()
    metrics = Metrics()
    metrics.add_token_usage(
        prompt_tokens=9_000,
        completion_tokens=500,
        cache_read_tokens=0,
        cache_write_tokens=0,
        context_window=20_000,
        response_id='pre-condense',
    )
    hud.update_from_llm_metrics(metrics)
    assert hud.state.context_tokens == 9_000

    hud.update_condensation_count(1)
    assert hud.state.context_tokens == 0

    metrics.add_token_usage(
        prompt_tokens=2_500,
        completion_tokens=100,
        cache_read_tokens=0,
        cache_write_tokens=0,
        context_window=20_000,
        response_id='post-condense',
    )
    hud.update_from_llm_metrics(metrics)

    assert hud.state.context_tokens == 2_500
    assert hud.state.context_limit == 20_000

def test_hud_marks_estimated_token_usage() -> None:
    hud = HUDBar()
    metrics = Metrics()
    metrics.accumulated_cost = 0.1
    metrics.add_token_usage(
        prompt_tokens=120,
        completion_tokens=30,
        cache_read_tokens=0,
        cache_write_tokens=0,
        context_window=8000,
        response_id='resp-est',
        usage_estimated=True,
    )

    hud.update_from_llm_metrics(metrics)

    assert hud.state.token_usage_estimated is True
    assert '~' in hud._format().plain

def test_hud_does_not_mark_provider_reported_usage_as_estimated() -> None:
    hud = HUDBar()
    metrics = Metrics()
    metrics.accumulated_cost = 0.1
    metrics.add_token_usage(
        prompt_tokens=120,
        completion_tokens=30,
        cache_read_tokens=0,
        cache_write_tokens=0,
        context_window=8000,
        response_id='resp-real',
        usage_estimated=False,
    )

    hud.update_from_llm_metrics(metrics)

    assert hud.state.token_usage_estimated is False
    assert '~' not in hud._format().plain

def test_hud_falls_back_to_response_latencies_for_call_count() -> None:
    hud = HUDBar()
    metrics = Metrics()
    metrics.accumulated_cost = 0.5
    metrics.response_latencies = [
        ResponseLatency(model='openai/gpt-5.1', latency=0.2, response_id='resp-1')
    ]

    hud.update_from_llm_metrics(metrics)

    assert hud.state.llm_calls == 1
    assert hud.state.cost_usd == 0.5

def test_hud_compact_workspace_label_shows_leaf_with_ellipsis() -> None:
    assert HUDBar.compact_workspace_label('~/projects/my-app') == '…/my-app'
    assert HUDBar.compact_workspace_label('C:/Users/dev/repos/Grinta') == '…/Grinta'
    assert HUDBar.compact_workspace_label('Grinta') == 'Grinta'

def test_hud_single_bar_format_all_widths() -> None:
    """HUD uses one dense bar (no wide/narrow mode split)."""
    hud = HUDBar()
    hud.state.model = 'openai/gpt-5.1'
    hud.state.context_tokens = 5000
    hud.state.context_limit = 128000
    hud.state.cost_usd = 0.1234
    hud.state.llm_calls = 3
    hud.state.ledger_status = 'Healthy'

    a = hud._format()
    b = hud._format_compact()
    c = hud._format_bar()
    assert a.plain == b.plain == c.plain
    assert '●' in a.plain
    assert '5K/128K' in a.plain or '5000' in a.plain
    assert 'M:?' in a.plain
    assert '3c' in a.plain
    assert '$0.123' in a.plain

def test_hud_ledger_icon() -> None:
    """HUD ledger icon returns correct single-char indicators."""
    hud = HUDBar()
    hud.state.ledger_status = 'Healthy'
    assert hud._ledger_icon() == '●'
    hud.state.ledger_status = 'Error'
    assert hud._ledger_icon() == '✗'
    hud.state.ledger_status = 'Paused'
    assert hud._ledger_icon() == '⏸'
