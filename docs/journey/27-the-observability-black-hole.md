# 26. The Observability Black Hole

When a deterministic system fails, you get a stack trace. A null pointer exception on line 42. A database timeout. You can write a unit test, fix the logic, and move on.

When an LLM agent fails, you get a hallucination buried in turn 48 of a conversation. You get a loop where it reads the same file three times, nods to itself, and then writes a completely incorrect regex. There is no stack trace for "the model forgot what the user asked because the context window filled up with `ls -la` outputs."

In the early days of Grinta, debugging was a nightmare. I would run the agent, watch it do something incredibly stupid, and then scroll through thousands of lines of raw terminal output trying to reconstruct its latent reasoning. It was an observability black hole. 

Other frameworks solve this by dumping everything into a massive JSON log file or forcing you to use external observability platforms like LangSmith or Helicone. But I wanted Grinta to be local-first and self-contained. I didn't want to rely on a SaaS product just to figure out why my agent was stuck.

## The Event Streams

The solution was treating the agent's execution not as a call-and-response loop, but as an append-only event stream (like I discussed in the architecture layer). Every thought, every tool call, every stdout chunk, every validation failure is emitted as a distinct event. 

But emitting events isn't enough; you have to *see* them. That's why the `cli/` module has specialized renderers (`event_renderer.py`, `reasoning_display.py`, `tool_call_display.py`). Because prompt debugging is UI design. If you can't see the exact moment the agent's mental model diverged from reality, you can't fix the prompt that caused it. 

I stopped tracing JSON and started streaming reasoning directly into the terminal, formatted beautifully by Rich and Textual components when they existed, and now through strict ANSI renderers.

## Compaction as Data Loss

The hardest part of tracing an agent is that the context window is a leaky bucket. As the session goes on, the context compactor kicks in to save tokens. It summarizes past turns. But when you are debugging *why* the agent made a decision at turn 50, you need to know exactly what it saw at turn 49. If turn 49 was summarized away, the evidence is gone.

This forced me to decouple *what the LLM sees* from *what the ledger records*. The ledger (`backend/ledger/`) is immutable and append-only. It never forgets. The compactor (`backend/context/compactors.py`) only modifies the payload sent to the API, not the historical record. When the agent fails, the ledger holds the truth, even if the model's memory has been compressed into oblivion.

Observability in agentic systems isn't about logging errors; it's about logging *intent*.

---

← [The Perfect Prompt Illusion](26-the-perfect-prompt-illusion.md) | [The Book of Grinta](README.md) | [Token Economics and the FinOps Trap](28-token-economics-and-the-finops-trap.md) →
