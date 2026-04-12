# 10. The Model-Agnostic Reckoning

There is a certain arrogance in building an AI agent around one language model.

It assumes the current king of the benchmarks will stay king forever. Worse, it treats one model's quirks as if they were universal intelligence.

When you hardcode your agent to OpenAI's function-calling schema, temperature settings, and JSON output expectations, you are not building a general agent. You are building an OpenAI client with extra steps.

If a better open-source model drops tomorrow, your agent breaks. If your user needs local models for privacy, your agent is useless.

Grinta is model-agnostic. Not as a marketing bullet point, but as a structural philosophy that forced me to rewrite the entire inference layer from scratch.

This chapter is about why that matters, and what model compatibility actually looks like in the trenches.

---

## The Illusion of the Generic API

In the beginning, I thought model-agnosticism meant using a library like LiteLLM to route calls. "Just swap the base URL and the model string."

That is naive for autonomous systems. It works for a chatbot. It catastrophically fails for an autonomous coding agent.

An autonomous coding agent relies completely on structured outputs, function calling, parameter extraction, and context window management. These are exactly the areas where LLM providers violently disagree on implementation.

OpenAI natively supports tools with JSON schema.
Anthropic supports XML-like `<tool_use>` blocks overlaid on an API schema.
Gemini has `function_declarations`.
Local models often have *no* native tool calling, meaning you have to prompt them into producing text that looks like a function call and parse it with regular expressions.

If you don't build an abstraction layer above these implementations, your agent logic becomes infected with provider-specific `if/else` statements. The prompt manager needs to know which model is running to decide how to format the system instructions. The parser needs to know. The orchestrator needs to know.

Soon, your entire codebase is just a giant switch statement based on `model_name`.

## The Three-Client Architecture

I realized that to be truly model-agnostic, I had to stop trusting third-party libraries to normalize everything. The abstraction had to be mine, and it had to sit right at the boundary between Grinta and the network.

The inference layer implements a true three-client architecture, plus an essential fallback:

1. **Native OpenAI Client:** Direct SDK integration for OpenAI models.
2. **Native Anthropic Client:** Direct SDK integration for Claude models.
3. **Native Gemini Client:** Direct SDK integration for Google GenAI models.
4. **OpenAI-Compatible Fallback:** The crucial fallback for everything else (Grok, DeepSeek, Mistral, Ollama, LM Studio, vLLM).

The provider resolver sits in front of this. It knows about eighteen provider prefixes: `anthropic`, `deepinfra`, `deepseek`, `fireworks`, `google`, `groq`, `lightning`, `lm_studio`, `mistral`, `nvidia`, `ollama`, `openai`, `openrouter`, `perplexity`, `replicate`, `together`, `vllm`, and `xai`. If you ask for `anthropic/claude-3-5-sonnet`, it routes to the Anthropic client. If you ask for `ollama/llama3`, it automatically discovers the local Ollama endpoint on port `:11434` and routes to the OpenAI-compatible proxy client.

Provider resolution is intentionally strict for configured models. Grinta trusts an explicit provider prefix or an exact catalog entry, and does not infer providers from model-name patterns. That distinction matters because loose inference — "oh, this model name contains 'claude' so it must be Anthropic" — breaks when providers start hosting each other's models or when proxy/aggregator services like OpenRouter and Lightning AI sit between you and the actual provider. Those aggregators need the `openai/` prefix for routing, and the resolver handles that explicitly.

### The Shared Connection Pool

One engineering detail that most people would never notice but that matters enormously at scale: the three clients share an httpx connection pool.

LLM SDKs use httpx internally. By default, each SDK client creates its own transport, wasting TCP connections when multiple sessions hit the same provider. Grinta's inference layer shares `httpx.Client` and `httpx.AsyncClient` instances keyed by `(provider, base_url)`. The pool limits are tuned: 20 max connections, 10 max keepalive connections, 120-second keepalive expiry. This means keep-alive connections are reused across sessions, reducing TLS handshake overhead and connection setup time.

When you are running a long autonomous session with hundreds of LLM calls, the difference between establishing a fresh TCP connection on every call and reusing a warm connection pool is measurable in both latency and reliability.

## Standardizing the Tools

The hardest part of this was normalizing the tool execution.

An agent does not just "ask" to use a tool. It emits a specialized message format. The provider SDK returns that specialized format.

Grinta normalizes *everything* back to the OpenAI schema internally.

When the Anthropic client receives a `<tool_use>` block, Grinta's mapper immediately intercepts it, formats the arguments as JSON, and wraps it in a synthetic OpenAI-style `tool_calls` array. When the agent uses a non-native local model without function calling support, Grinta uses an XML-to-JSON fallback converter that parses generic text shaped like `<function=read_file><parameter=path>main.py</parameter></function>` and silently turns it into the exact same OpenAI-style function call object.

The fallback converter is a piece of engineering I am quietly proud of. The pseudo-XML contract allows flexible spacing around tags, uses non-greedy matching up to the first literal `</parameter>` to avoid ambiguity, and ships with stop words like `</function>` for streaming boundaries. Tool results on the user side use strict structured payload blocks — `<app_tool_result_json>{"tool_name":"...","content":...}</app_tool_result_json>` — that guarantee deterministic round-trip parsing. No ambiguous free-text parsing. No heuristic guessing.

The converter tracks its own telemetry: strict parse success, strict parse failure, and malformed payload rejection counters. Because when the fallback path silently fails, you need to know about it before the user does.

The orchestrator never knows what model it is talking to. It only ever sees standard function calls.

## The Catalog Over Hardcoding

Then comes the issue of model parameters.

Some models support `temperature`. O1 and O3 "thinking" models do not.
Some models support `top_p`.
Some models have a specific parameter for reasoning effort or thinking budgets.
Some models support prompt cache hints. Some do not.
Some models accept stop words. Some break if you send them.
Some models support structured response schemas. Some ignore them.

If you write your inference layer with hard-coded rules like `if model.startswith('o1'): del payload['temperature']`, you are fighting a losing battle against the release cycle of the AI industry.

Grinta solved this with a data-driven catalog and a capability system. The `ModelFeatures` dataclass carries frozen capability flags: `supports_function_calling`, `supports_reasoning_effort`, `supports_prompt_cache`, `supports_stop_words`, and `supports_response_schema`. Each capability is resolved by matching the model name against pattern lists — glob patterns that match against the normalized model basename or, for provider-qualified patterns containing a `/`, against the full model string including the provider prefix.

Model name normalization is its own small discipline. The resolver trims whitespace, lowercases, strips provider prefixes to extract the canonical basename, and drops trailing `-gguf` suffixes because local model files carry format identifiers that have nothing to do with capability. Two model strings that describe the same model but look different textually get normalized to the same canonical name.

This means adding support for a new model is often a data change — adding a pattern to a list — instead of writing conditional code. When a new model family launches with unusual behavior, I update the catalog. I do not rewrite the inference logic.

## The LLM Exception Mapper

When Claude throws an over-limit error, it looks different than when Gemini does the same thing. When OpenAI returns a 408, it means timeout. When it returns a 503, it means service unavailable. Anthropic returns a `BadRequestError` with a message about maximum context length. Google throws a completely different SDK exception.

Grinta's LLM exception mapper normalizes all of these into a standard hierarchy: `ContextWindowExceededError`, `RateLimitError`, `AuthenticationError`, `ContentPolicyViolationError`, `ServiceUnavailableError`, `NotFoundError`, `InternalServerError`. The mapper processes API status errors by HTTP code, checks bad-request errors for context-window-specific language, and wraps everything else in a provider-labeled `ModelProviderError`.

This is critical because the recovery service — the orchestrator component that decides whether to retry, back off, or hard-stop — must not care which provider threw the error. It cares only about the *category* of the error. An authentication failure from Anthropic and an authentication failure from OpenAI must both produce the same behavior: immediate stop, surface to the user, do not retry.

Without this normalization layer, error handling in an agent becomes a nest of provider-specific `try/except` blocks that multiply every time a new provider is added. With it, error handling is written once against a clean hierarchy, and new providers just need a mapper.

---

## The LLM Response Contract

One more detail that matters: the response object itself.

Every LLM call in Grinta returns an `LLMResponse` — a custom object that provides both attribute access and dictionary access to the same data. That dual interface exists because some parts of the codebase naturally read `response.content` while others naturally read `response['choices']`, and enforcing a single style across thousands of call sites would produce more boilerplate than clarity.

The response carries the raw content, the parsed tool calls, stop reason, token usage (prompt tokens, completion tokens, total), and provider metadata. The token usage tracking feeds directly into the cost quota middleware: every response updates a running total, and the middleware blocks new calls when the budget cap is reached.

The stop reason normalization matters more than you might expect. OpenAI returns `stop` for completed responses and `tool_calls` when the model wants to use a tool. Anthropic returns `end_turn` and `tool_use`. Gemini has its own vocabulary. The response mapper normalizes all of these to a standard set so the orchestrator can make decisions like "should I continue stepping?" without knowing which provider is active.

---

## The Lesson of the Reckoning

Why go to all this trouble?

Because events do not lie. Models do. Models change. Startups pivot. Pricing goes up. Open-source models get better.

If your agent is tied to one model's API syntax, your architecture is renting space in someone else's walled garden. When they move the walls, you die.

The decision to build the inference layer this way was expensive. It took weeks to design, test, debug across providers, and ensure error handling was normalized natively. It means maintaining three client implementations plus a fallback, keeping the capability catalog current as models launch, and updating the exception mapper when providers change their error formats.

But the alternative — depending on a framework's abstraction or a single provider's SDK — creates a dependency that compounds over time. Every month that passes, every new model launch, and every pricing shift validates that investment. Grinta can switch from Claude to GPT to Gemini to a local Ollama model with a single config change. No code change. No adapter. No migration.

Grinta is model-agnostic because it is the only way to build an agent that can survive next year.

---

← [The 3 AM Decisions](09-the-3am-decisions.md) | [The Book of Grinta](README.md) | [The Console Wars](11-the-console-wars.md) →
