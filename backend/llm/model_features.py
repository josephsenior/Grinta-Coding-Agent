"""Model capability detection helpers used to gate Forge LLM features."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch


def normalize_model_name(model: str) -> str:
    """Normalize a model string to a canonical, comparable name.

    Strategy:
    - Trim whitespace
    - Lowercase
    - If there is a '/', keep only the basename after the last '/'
      (handles prefixes like openai/, anthropic/, etc.)
      and treat ':' inside that basename as an Ollama-style variant tag to be removed
    - There is no provider:model form; providers, when present, use 'provider/model'
    - Drop a trailing "-gguf" suffix if present
    """
    raw = (model or "").strip().lower()
    if "/" in raw:
        name = raw.split("/")[-1]
        if ":" in name:
            name = name.split(":", 1)[0]
    else:
        name = raw
    return name.removesuffix("-gguf")


def model_matches(model: str, patterns: list[str]) -> bool:
    """Return True if the model matches any of the glob patterns.

    If a pattern contains a '/', it is treated as provider-qualified and matched
    against the full, lowercased model string (including provider prefix).
    Otherwise, it is matched against the normalized basename.
    """
    raw = (model or "").strip().lower()
    name = normalize_model_name(model)
    for pat in patterns:
        pat_l = pat.lower()
        if ("/" in pat_l and fnmatch(raw, pat_l)) or ("/" not in pat_l and fnmatch(name, pat_l)):
            return True
    return False


from backend.llm.capabilities import ModelCapabilities


@dataclass(frozen=True)
class ModelFeatures(ModelCapabilities):
    """Capabilities and limits reported for a particular LLM provider/model pair."""

    max_input_tokens: int | None = None
    max_output_tokens: int | None = None


FUNCTION_CALLING_PATTERNS: list[str] = [
    "claude-3-7-sonnet*",
    "claude-3.7-sonnet*",
    "claude-3-5-sonnet*",
    "claude-3.5-haiku*",
    "claude-sonnet-4*",
    "claude-opus-4-1*",
    "gpt-4o*",
    "gpt-4.1*",
    "gpt-5*",
    "o1-*",
    "o3-*",
    "o4-*",
    "gemini/gemini-1.5-*",
    "gemini/gemini-2.0-*",
    "gemini-2.5-*",
    "grok-*",
    "kimi-k2*",
    "qwen3*",
]
REASONING_EFFORT_PATTERNS: list[str] = [
    "o1-*",
    "o3-*",
    "o4-*",
    "gemini-2.0-flash-thinking*",
    "gemini-2.5-*",
    "gpt-5*",
    "deepseek*",
]
PROMPT_CACHE_PATTERNS: list[str] = [
    "claude-3-7-sonnet*",
    "claude-3.5-sonnet*",
    "claude-3.5-haiku*",
    "claude-3-haiku*",
    "claude-3-opus*",
    "claude-sonnet-4*",
]
SUPPORTS_STOP_WORDS_FALSE_PATTERNS: list[str] = [
    "o1*",
    "xai/grok-4*",
    "deepseek*",
]


RESPONSE_SCHEMA_PATTERNS: list[str] = [
    "gpt-4o*",
    "gpt-4-turbo*",
    "o1-*",
    "o3-*",
    "gemini/gemini-1.5-*",
    "gemini/gemini-2.0-*",
    "claude-3-7-sonnet*",
    "claude-3.5-sonnet*",
    "claude-3.5-haiku*",
]


def get_model_token_limits(model: str) -> tuple[int | None, int | None]:
    """Get max input and output token limits for a model.
    """
    from backend.llm.catalog_loader import get_token_limits

    return get_token_limits(model)


def get_features(model: str) -> ModelFeatures:
    """Get feature capabilities for a specific model.

    Args:
        model: Model identifier

    Returns:
        ModelFeatures object with capability flags

    """
    max_input, max_output = get_model_token_limits(model)
    return ModelFeatures(
        max_input_tokens=max_input,
        max_output_tokens=max_output,
        supports_function_calling=model_matches(model, FUNCTION_CALLING_PATTERNS),
        supports_reasoning_effort=model_matches(model, REASONING_EFFORT_PATTERNS),
        supports_prompt_cache=model_matches(model, PROMPT_CACHE_PATTERNS),
        supports_stop_words=not model_matches(model, SUPPORTS_STOP_WORDS_FALSE_PATTERNS),
        supports_response_schema=model_matches(model, RESPONSE_SCHEMA_PATTERNS),
    )
