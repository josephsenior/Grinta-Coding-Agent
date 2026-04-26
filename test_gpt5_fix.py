import json
from backend.inference.catalog_loader import apply_model_param_overrides, lookup

def test_gpt5_nano_overrides():
    model = "openai/gpt-5-nano"
    entry = lookup(model)
    print(f"Model Entry for {model}:")
    print(f"  strip_temperature: {entry.strip_temperature}")
    print(f"  strip_top_p: {entry.strip_top_p}")
    print(f"  strip_penalties: {entry.strip_penalties}")
    print(f"  use_max_completion_tokens: {entry.use_max_completion_tokens}")

    call_kwargs = {
        "model": "gpt-5-nano",
        "temperature": 0.5,
        "top_p": 0.9,
        "presence_penalty": 0.1,
        "frequency_penalty": 0.1,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "hi"}]
    }

    result = apply_model_param_overrides(model, call_kwargs)
    print("\nResulting call_kwargs:")
    print(json.dumps(result, indent=2))

    assert "temperature" not in result
    assert "top_p" not in result
    assert "presence_penalty" not in result
    assert "frequency_penalty" not in result
    assert "max_tokens" not in result
    assert result["max_completion_tokens"] == 1024
    print("\nAll assertions passed!")

if __name__ == "__main__":
    test_gpt5_nano_overrides()
