# 27. Token Economics and the FinOps Trap

The first time I let the multi-agent swarm run on a medium-sized refactoring ticket, it burned through $40 of Claude 3.5 Sonnet tokens in thirty minutes.

That was not a bug. That was the architecture doing exactly what I had designed it to do: decompose the task, spawn specialized agents, let each one reason independently, and re-prompt whenever output did not match the expected schema. The problem was that every re-prompt added another 8,000 tokens to the session, and the session had no ceiling.

The FinOps trap of agentic frameworks is simple: **loops compound exponentially**. If an agent hallucinates a tool call, the tool returns a 10,000-line error trace, and the agent reads that trace to decide what to do next, you are suddenly paying for 10,000 tokens per turn just to watch the agent be confused. And if the agent is confused, it loops. And if it loops, the next turn is even more expensive because the context window is now full of the previous confusion.

I learned this the hard way. Then I built the machinery to stop it.

---

## The Iteration Cap

The first defense is the simplest: a hard iteration cap in the orchestration loop.

```python
# backend/orchestration/orchestration_config.py
budget_per_task_delta: float | None = None
```

An agent that has not solved the problem in 30 steps is almost never going to solve it in 31. It is stuck in a local minimum. The `IterationGuardService` tracks step counts and can halt the loop before it burns through another dollar of tokens on a dead path.

This is not elegant. It is a circuit breaker. And circuit breakers do not need to be elegant — they need to fire.

## The HUD as a FinOps Instrument

The HUD bar (`backend/cli/hud.py`) tracks four numbers in real time:

- **Context tokens** — how much of the window is consumed
- **Cost in USD** — accumulated spend for the session
- **LLM calls** — total round-trips to the provider
- **Condensation count** — how many times context has been compacted

This is not decoration. It is the agent's financial instrument. The renderer (`backend/cli/event_renderer.py`) watches `cost_usd` against `max_budget_per_task` and emits warnings at 80% and hard stops at 100%. The budget check is not a suggestion — it is a gate in the middleware pipeline.

```python
# backend/cli/event_renderer.py — _check_budget()
if cost >= self._max_budget and not self._budget_warned_100:
    self._budget_warned_100 = True
    # ... emit hard stop
```

The point is not to prevent the agent from working. The point is to make the cost visible *before* the session becomes a financial surprise.

## Context Compaction as Cost Control

Compaction is not just about fitting within the context window. It is about budget.

Every turn that adds 4,000 tokens of command output to the history is a turn that makes the next API call 4,000 tokens more expensive. The compaction system (`backend/core/rollback/rollback_manager.py` and the compactor implementations) truncates verbose outputs, summarizes old turns, and strips redundant tool results. The auto-selector picks strategy based on session shape — aggressive truncation for command-heavy sessions, structured summaries for reasoning-heavy ones.

The math is direct: if compaction saves 20,000 tokens per session, and the model costs $15/M tokens, that is $0.30 saved per session. Over 100 sessions, that is $30. Over 1,000, that is $300. Compaction pays for itself.

## High/Low Routing

Not every turn needs a frontier model.

Checking whether a bash command exited with `0` does not require Claude Sonnet. Parsing a JSON tool response does not require GPT-4o. The architecture supports routing between model tiers — cheaper, faster models for confirmation and extraction tasks, expensive reasoning models for orchestration and planning.

The current implementation does not auto-route (that is still experimental), but the provider resolver (`backend/inference/`) and the three direct client families make it possible. The function-call converter for models without native tool calling means even a local 8B model can participate in the tool loop — it just needs more guardrails.

## The Receipt

Here is what the cost discipline looks like in practice, after the SaaS dream died:

| Metric | SaaS Phase (multi-agent) | Current (single agent) |
|---|---|---|
| Avg tokens per task | 80K–200K | 15K–50K |
| Avg cost per task | $5–$40 | $0.20–$2.00 |
| Stuck detection | None | 10 heuristics + circuit breaker |
| Budget gate | None | 80% warning, 100% hard stop |
| Context compaction | None | 9 strategies, auto-selected |

The single agent is not just more reliable. It is **20× cheaper per task**. That is not a coincidence. It is the result of deleting the parts of the architecture that made cost invisible.

The FinOps trap forces you to become a better architect. Not because you want to, but because the bill arrives whether you are ready or not.

---

← [The Observability Black Hole](27-the-observability-black-hole.md) | [The Book of Grinta](README.md) | [The Latency Veil and Human Trust](29-the-latency-veil-and-human-trust.md) →
