# Local models

Grinta can use local models through an OpenAI-compatible HTTP endpoint. Ollama
and LM Studio run the model; Grinta sends chat-completion requests and converts
their responses into its provider-independent `LLMResponse` format.

## Ollama

1. Install Ollama, then start it with `ollama serve`.
2. Download a model, for example `ollama pull llama3`.
3. Set the following values in `settings.json`:

```json
{
  "llm_provider": "ollama",
  "llm_model": "ollama/llama3",
  "llm_api_key": "${LLM_API_KEY}",
  "llm_base_url": "http://localhost:11434/v1",
  "llm_context_window_tokens": 8192,
  "llm_max_output_tokens": 2048
}
```

No API key is required for the default local Ollama server. If Ollama runs on a
different host, replace `llm_base_url`; `OLLAMA_HOST` is also supported.

## LM Studio

1. Download a model in LM Studio.
2. Load it and start LM Studio's local server.
3. Copy the model identifier exposed by the server into `settings.json`:

```json
{
  "llm_provider": "lm_studio",
  "llm_model": "lm_studio/mistral-7b-instruct",
  "llm_api_key": "${LLM_API_KEY}",
  "llm_base_url": "http://localhost:1234/v1",
  "llm_context_window_tokens": 8192,
  "llm_max_output_tokens": 2048
}
```

The model identifier must match the value returned by the server's `/v1/models`
endpoint. Change the URL when LM Studio uses a non-default port.

## Minimum model requirements

- The server must implement OpenAI-compatible `/v1/models` and
  `/v1/chat/completions` endpoints.
- Configure the model's real context window. Grinta reserves 4,096 tokens for
  protocol overhead in addition to the output budget, so an 8K context is a
  practical minimum for small tasks; 16K or more is preferable for repository
  work.
- Native tool calling is optional for plain-text responses. To perform actions,
  the model must either support OpenAI-style tool calls or use Grinta's text
  fallback and follow its injected tool syntax reliably.
- Streaming is optional. The same model must return at least one completion
  choice in non-streaming mode.

## Compatibility behavior

- Non-streaming text, truncated responses, and OpenAI-style tool calls are
  normalized through the same client used for hosted OpenAI-compatible APIs.
- Streaming responses are accumulated into one final response. Grinta preserves
  the terminal `finish_reason`, including `length` and `tool_calls`.
- Setting `native_tool_calling` to `false` in an `LLMConfig` forces Grinta's text
  tool-call fallback, even when the provider is generally tool-capable.

## Limitations

- Tool-call quality and schema compliance depend on the selected model. Some
  local models only produce reliable plain text.
- A `length` finish reason means the server stopped at its output limit; increase
  the configured output limit or simplify the request before retrying.
- A server that omits its terminal finish reason cannot distinguish truncation
  from a normal stop.
- The fixture tests validate protocol compatibility without downloading models
  or starting Ollama or LM Studio. They do not benchmark model quality, latency,
  memory use, or hardware support.

## Contributor tests

Recorded responses live in `backend/tests/fixtures/local_models`. Run them with:

```bash
PYTHONPATH=. uv run pytest backend/tests/unit/inference/test_local_model_compatibility.py
```

The existing Python CI inference shard runs `backend/tests/unit/inference` on
every pull request, so these tests are automatically included without requiring
a live local-model server.
