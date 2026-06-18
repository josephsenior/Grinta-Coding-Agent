# 25. The Observability, Cost, and Latency Triad

When a deterministic system fails, you get a stack trace. A null pointer exception on line 42. A database timeout. You can write a unit test, fix the logic, and move on.

When an LLM agent fails, you get a hallucination buried in turn 48 of a conversation. You get a loop where it reads the same file three times, nods to itself, and then writes a completely incorrect regex. There is no stack trace for *"the model forgot what the user asked because the context window filled up with `ls -la` outputs."*

In the early days of Grinta, debugging was a nightmare. I would watch the agent do something completely incorrect, and then scroll through thousands of lines of raw terminal output trying to reconstruct its latent reasoning. It was an observability black hole.

Other frameworks solve this by dumping everything into a massive cloud logging database. But I wanted Grinta to be local-first, self-contained, cost-disciplined, and trusted. That required solving the triad: **observability, economics, and trust.**

---

## The Event-Sourced Ledger

The first foundation was treating the agent's execution not as a call-and-response loop, but as an append-only event stream. Every thought, every tool call, every stdout chunk, every validation failure is emitted as a distinct event. 

Decoupling *what the LLM sees* from *what the ledger records* is critical. As the session goes on, context compaction runs to save tokens. It summarizes past turns. But when you are debugging *why* the agent made a decision at turn 50, you need to know exactly what it saw at turn 49. If turn 49 was summarized away, the evidence is gone. 

The ledger is immutable and append-only. The compactor only modifies the payload sent to the API, not the historical record. When the agent fails, the ledger holds the truth, even if the model's memory has been compressed into oblivion.

### SQLite Authoritative Schema

For long, high-throughput sessions, writing individual JSON files to disk becomes a bottleneck. Grinta utilizes a single local SQLite database (`events.db`) per conversation as an append-only ledger accelerator, built on thread-safe WAL (Write-Ahead Logging) write serialization:

```sql
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    timestamp   REAL    NOT NULL,
    event_type  TEXT    NOT NULL,
    source      TEXT,
    payload     TEXT    NOT NULL          -- JSON blob
);

CREATE INDEX IF NOT EXISTS idx_events_type   ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);

CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

### Ledger Event Payload

A typical serialized event in the `payload` column captures the raw input arguments, the source, and a verification checksum to guarantee ledger integrity on startup:

```json
{
  "id": 42,
  "timestamp": 1779234000.123,
  "action": "run_command",
  "source": "agent",
  "arguments": {
    "CommandLine": "pytest tests/",
    "Cwd": "c:\\Users\\GIGABYTE\\Desktop\\Grinta"
  },
  "checksum": "a8f3b2cd78a1bc498bf0d35e"
}
```

---

## Token Economics and the FinOps Trap

The first time I let the multi-agent swarm run on a medium refactoring ticket, it burned through $40 of Claude Sonnet tokens in thirty minutes. Every re-prompt added another 8,000 tokens to the session.

The FinOps trap of agentic frameworks is simple: **loops compound exponentially**. If an agent hallucinates a tool call, the tool returns a 10,000-line error trace, and the agent reads that trace to decide what to do next, you are paying for 10,000 tokens per turn just to watch the agent be confused. And if the agent is confused, it loops.

### The Budget Gate Middleware

The renderer watches `cost_usd` against the configured task limit and halts the loop before it burns budget on a dead path. The budget check is implemented directly in `backend/cli/event_renderer.py`:

```python
def _check_budget(self) -> None:
    if not self._max_budget or self._max_budget <= 0:
        return
    cost = self._hud.state.cost_usd
    if cost >= self._max_budget and not self._budget_warned_100:
        self._budget_warned_100 = True
        self._print_or_buffer(
            Panel(
                Text(
                    f'Budget limit reached: ${cost:.4f} / ${self._max_budget:.4f}',
                    style=CLR_ERR_ICON,
                ),
                title=Text('Budget Exceeded', style=CLR_ERR_ICON),
                border_style=CLR_STATUS_ERR,
                padding=(1, 2),
            )
        )
    elif cost >= self._max_budget * 0.8 and not self._budget_warned_80:
        self._budget_warned_80 = True
        self._print_or_buffer(
            Panel(
                Text(
                    f'Approaching budget: ${cost:.4f} / ${self._max_budget:.4f} (80%)',
                    style=CLR_WARN_BODY,
                ),
                title=Text('Budget Warning', style=CLR_WARN_ICON),
                border_style=CLR_STATUS_WARN,
                padding=(1, 2),
            )
        )
```

The HUD bar tracks four metrics in real time:
* **Context tokens** — how much of the window is consumed.
* **Cost in USD** — accumulated spend for the session.
* **LLM calls** — total round-trips to the provider.
* **Condensation count** — how many times context has been compacted.

---

## The Latency Veil and Human Trust

A human staring at a blinking cursor for 45 seconds does not feel like the agent is working. They feel like it has crashed.

This is the latency veil: the gap between what the agent is doing (calling the inference client, reading files, running tests) and what the human perceives (nothing). Spinning loaders confirm the process has not crashed, but they do not show *what* the process is doing.

### Streaming Intent

The event-sourced architecture made the solution possible: stream every tool execution as it happens, not after it completes. The reasoning display streams the agent's intermediate thoughts and intent as they arrive, not as a batch after the turn completes. 

```
[TOOL] read(type="file", path="tests/conftest.py")
[TOOL] run_command(pytest tests/)
[LLM] The test failed because of a missing fixture. I need to edit conftest.py.
[TOOL] replace_string(path="tests/conftest.py") — exact anchor edit
```

### Confirmation Middleware & Autonomy Knob

Trust is also about blast radius. If an agent wants to run a destructive command, the security command analyzer catches it. High-risk commands pause the loop and present the human with a choice:

```
The agent wants to execute: rm -rf /tmp/grinta-scratch/
Risk level: HIGH (recursive deletion)
Allow? [Y/N]
```

The confirmation system is controlled by the autonomy mode (`balanced`, `full`, `conservative`), which the user can toggle mid-session via `/autonomy`:
* `full`: Fast but risky. The agent runs without interruption.
* `conservative`: Safe but slow. Almost every write requires approval.
* `balanced` (default): Trust the agent for reads and safe edits, intercept destructive actions.

---

## The Receipts

Here is what the operational economics look like in practice:

| Metric | SaaS Phase (multi-agent) | Current (single agent) |
|---|---|---|
| Avg tokens per task | 80K–200K | 15K–50K |
| Avg cost per task | $5–$40 | $0.20–$2.00 |
| Stuck detection | None | Hard-signal control path + telemetry heuristics + circuit breaker |
| Budget gate | None | 80% warning, 100% hard stop |
| Context compaction | None | ~10 strategies, auto-selected |

The single agent is not just more reliable. It is **20× cheaper per task**. The cost discipline is not a luxury — it is what makes autonomous execution viable.

---

← [The Parallelization Trap](25-the-parallelization-trap.md) | [The Book of Grinta](README.md) | [The Weight Divide: Local vs Hosted](30-the-weight-divide-local-vs-hosted.md) →
