# 26. The Weight Divide: Local vs Hosted

Being model-agnostic means Grinta connects to Claude on Anthropic's API, GPT on OpenAI, Gemini on Google, or Llama running on a local Ollama instance. But supporting them was not about putting different HTTP clients in a switch statement.

It exposed a fundamental architectural divide that most agent frameworks pretend does not exist: **relying on API capability versus relying on local honesty**.

---

## The Local Promise

The dream was clean: run a local model, pay zero dollars per token, never leak proprietary source code to a remote server. Complete autonomy, complete privacy.

The reality was messier.

An 8B parameter model is fast but struggles with complex tool-call schemas. It hallucinates parameters. It forgets the system prompt after 40 turns. The function-call converter (`backend/inference/`) catches some of this — it translates non-native tool calling into the structured format the engine expects — but it cannot fix reasoning quality. If the model does not understand the task, no amount of schema conversion will help.

A 70B model solves the reasoning problem but introduces a different one: it needs massive GPU VRAM, which breaks the "runs on a student's laptop" promise. And even then, generating 1,000 tokens locally can take 30 seconds, which turns the orchestration loop into a patience test.

## The Frontier Edge

The opposite extreme is cleaner but has its own costs. Claude Sonnet or GPT-4o gives near-magical tool adherence and reasoning power. But it introduces API latency, rate limits, network errors, and a context window that grows with every turn. A 60K token session sends that payload back and forth on every call, and each round-trip costs money.

The frontier models also have a different failure mode: they are *too* capable. A model that can reason about anything will reason about things it should not — exploring tangential solutions, over-engineering simple tasks, producing elegant but unnecessary abstractions. The prompt discipline chapters (15, 25, 26) are largely about constraining this capability into focused execution.

## The Bridge: Standardized Adapters

The solution was not to pick a winner. It was to standardize the communication layer so the engine does not care what is on the other end.

Grinta has three direct client families:

- **OpenAI-compatible** — covers OpenAI, Azure, OpenRouter, and any provider implementing the OpenAI chat completions API
- **Anthropic-native** — direct client for Claude with tool-use protocol
- **Google-native** — direct client for Gemini with its own tool schema

The provider resolver (`backend/inference/`) normalizes tool calling schemas across all three. OpenAI uses JSON Schema functions. Anthropic uses its own tool format. Gemini has yet another. The engine expects one thing: structured reasoning with typed tool calls. The adapters handle the translation.

But the deeper lesson was about **defensive architecture**. The validation subsystem (`backend/validation/`) catches malformed tool responses and returns error formats the LLM can read to self-correct. If a local model hallucinates a tool format, the system does not crash — it tells the model what went wrong and gives it another chance.

You build against the frontier APIs because they work. But you architect the system's defenses assuming you are running against a local model that might forget the prompt at any moment. That is what true resilience looks like.

## The Circuit Breaker as Model-Agnostic Insurance

The circuit breaker service (`backend/orchestration/agent_circuit_breaker.py`) is where this philosophy first became concrete. It tracks consecutive errors, adapts thresholds based on task complexity, and can halt the loop when the model is clearly not recovering. It does not care *which* model is failing — it only cares that the failure pattern matches a known stuck signature.

Current note: that logic is now also part of the broader operation pipeline through `backend/orchestration/services/circuit_breaker_service.py` and `backend/orchestration/middleware/circuit_breaker.py`. The responsibility did not disappear; it moved from "one clever guard" toward a layered control-plane concern.

This is the model-agnostic principle in action: the system's reliability layer is indifferent to the model. It measures behavior, not capability. A local model that recovers quickly gets more rope. A frontier model that loops gets cut off sooner. The circuit breaker treats them identically because the failure pattern is the same.

## The Honest Trade-Off

Here is the trade-off I landed on, and it is not a compromise — it is a design choice:

- **Default to frontier models** for their reasoning quality and tool discipline.
- **Support local models** for privacy, cost, and offline use — but with the expectation that they will need more guardrails.
- **Build the system's defenses around the weakest model**, not the strongest. If it works with a confused 8B model, it will work with anything.

The weight divide is not a problem to solve. It is a spectrum to design for. And designing for the bottom of the spectrum is what makes the top of the spectrum reliable.

---

← [The Observability, Cost, and Latency Triad](27-the-observability-black-hole.md) | [The Book of Grinta](README.md) | [The Two Lives of the Terminal](32-the-two-lives-of-the-terminal.md) →
