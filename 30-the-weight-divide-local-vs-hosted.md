# 29. The Weight Divide: Local vs Hosted

Being model-agnostic means Grinta can connect to Claude 3.5 on Anthropic’s API, GPT-4o on OpenAI, or Llama 3 running on a local Ollama instance. But supporting them natively in `backend/inference/` wasn’t just about putting different HTTP clients in a `switch` statement.

It exposed a fundamental architectural divide: relying on API latency vs. relying on heavy local weights.

## The Promise of Local Open Weights

The dream was complete local autonomy. You run DeepSeek or Llama 3 locally, pay zero dollars per token, and the agent works forever. You never leak your proprietary source code to a remote server.

But I quickly learned that running a local 8B parameter model is very different from running a 70B parameter model. An 8B model is fast but struggles with complex tool-call schemas. It hallucinates parameters. It struggles to hold context over 40 turns. If you run a larger model (70B) locally, you need massive GPU VRAM, which ruins the "runs on a student's laptop" promise. And even then, generating 1000 tokens locally can take a long time, slowing down the orchestration loop (`backend/orchestration/`).

## The Edge of the Frontier

Conversely, relying on Claude 3.5 Sonnet or GPT-4o gives you near-magical tool adherence and reasoning power, but introduces API latency, rate limits, and network errors. If your session creates a 60K token context window, sending it back and forth to an API takes seconds per turn.

## Bridging the Divide

In Grinta, the solution wasn't picking a winner. It was standardizing the communication layer. As I discussed in Chapter 10, the model-agnostic design meant I had to normalize tool calling schemas. OpenAI uses JSON Schema functions; Anthropic uses its own tool format.

By building standardizing adapters, I ensured that the `engine` didn't care what was on the other end of the network call. It just expected structured reasoning.

But more practically, this divide taught me that a production agent framework needs to assume the model might be slightly broken. If the local model hallucinates a tool format, the `validation/` subsystem catches it and returns an error format the LLM can read to correct itself.

You build against the frontier APIs because they work, but you architect the system's defenses assuming you're running against a local model that might forget the prompt at any moment. That is what true resilience looks like.

---

← [The Latency Veil and Human Trust](29-the-latency-veil-and-human-trust.md) | [The Book of Grinta](BOOK_OF_GRINTA.md) | [The Myth of the Committee](31-the-myth-of-the-committee.md) →
