"""Tests for prompt cache hint eligibility and OpenAI message sanitization."""

from __future__ import annotations

from backend.llm.mappers.openai import strip_prompt_cache_hints_from_messages
from backend.llm.prompt_caching import model_supports_prompt_cache_hints


def test_model_supports_hints_for_catalog_claude() -> None:
    assert model_supports_prompt_cache_hints("claude-4-sonnet")
    assert model_supports_prompt_cache_hints("anthropic/claude-4-sonnet")


def test_model_supports_hints_pattern_claude3() -> None:
    assert model_supports_prompt_cache_hints("claude-3.5-sonnet-20241022")


def test_model_supports_hints_gemini_pattern() -> None:
    assert model_supports_prompt_cache_hints("gemini/gemini-2.0-flash")
    assert model_supports_prompt_cache_hints("gemini-2.5-pro")


def test_model_supports_hints_openai_false() -> None:
    assert not model_supports_prompt_cache_hints("gpt-4o")
    assert not model_supports_prompt_cache_hints("openai/gpt-5")


def test_model_supports_hints_empty() -> None:
    assert not model_supports_prompt_cache_hints("")
    assert not model_supports_prompt_cache_hints("   ")


def test_strip_prompt_cache_hints_from_messages() -> None:
    messages = [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": "hi",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "cache_control": {"type": "ephemeral"},
        }
    ]
    original_cc = messages[0]["cache_control"]
    cleaned = strip_prompt_cache_hints_from_messages(messages)
    assert "cache_control" not in cleaned[0]
    assert "cache_control" not in cleaned[0]["content"][0]
    assert "cache_control" in messages[0]
    assert original_cc == messages[0]["cache_control"]
