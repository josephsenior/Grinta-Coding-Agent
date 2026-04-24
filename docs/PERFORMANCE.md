# Grinta Performance Guide

Reference targets and tuning levers for a single-user CLI session.

## Latency targets (single-user, local CLI)
These are the targets the project aims for; numbers vary substantially by model and workload.

| Step | Target p50 | Target p95 | Notes |
|---|---|---|---|
| Tool dispatch (in-process) | < 30 ms | < 150 ms | File read/write, search_code |
| `search_code` over a 100k-LoC repo | < 400 ms | < 1.5 s | Ripgrep fast path |
| AST edit (single symbol) | < 200 ms | < 800 ms | tree-sitter parse + replace |
| LLM round-trip (Sonnet/4o, ~10k ctx) | 1–3 s | 6–10 s | Network-bound |
| Full agent step (think + tool + observe) | 2–5 s | 10–20 s | Dominated by LLM |
| Crash-recovery WAL replay | < 500 ms / 1k events | < 2 s / 10k events | Local file store |

If you observe latencies meaningfully worse than p95 targets, investigate before tuning further.

## Token-budget targets
| Component | Soft cap | Hard cap | Notes |
|---|---|---|---|
| System prompt (no MCP) | 6 k | 10 k | Run `python -m backend.engine.prompts.prompt_builder` to measure |
| MCP tool block | 2 k | 6 k | Now rendered as a per-turn user-role addendum so it doesn't break prefix cache |
| Per-turn workspace context | 1 k | 3 k | Repo info + runtime info + secrets descriptions |
| Per-turn history (after compaction) | 60 % of model context | 80 % | Auto-compaction kicks in beyond soft cap |

## Tuning levers
- **`/compact`** — manually condense history when context gets tight.
- **`enable_internal_task_tracker`** — improves long-task discipline at a small token cost.
- **`enable_think`** — improves weak-model success at a moderate token cost; usually not needed for o1/r1/deepseek-reasoner.
- **Disable unused MCP servers** — every connected server adds tools to the prompt.
- **Use `--model`** to switch to a cheaper model for routine tasks (`gpt-4o-mini`, `gemini-2.5-flash`, local 7B).
- **Cost guard:** set `permissions.max_cost_per_task` in `settings.json` to a dollar cap; the rate governor will stop the agent if exceeded.

## Throughput and parallelism
- File-store writes go through a dedicated durable-writer thread — producers are not blocked.
- Multi-agent `delegate_task(parallel=True)` runs workers concurrently with an isolated event stream each.
- `search_code` uses ripgrep when available; otherwise falls back to a Python implementation that is ~5–20× slower.

## Memory footprint
- Idle REPL: ~150 MB
- Mid-task with semantic RAG warm: ~600 MB–1.2 GB (ChromaDB + sentence-transformers)
- Long sessions: bounded by auto-compaction; if memory grows unboundedly, file an issue.

## Measuring
- **Per-turn cost / tokens / latency:** visible in the HUD bar at all times.
- **System prompt size:** `python -m backend.engine.prompts.prompt_builder`.
- **Audit log:** `.grinta/storage/<session>/audit/` contains per-action timing and classification.
- **Provider-side latency:** check the LLM provider dashboard if HUD round-trips look slow.
