# Agent Eval Pack

This repo now includes a vendor-neutral evaluation pack for comparing Grinta against strong coding-agent baselines such as Claude Code, Aider, OpenHands, and Copilot-style autonomous loops.

The important constraint is honesty: this repo can score results from those systems, but it does not pretend to directly automate all of their control planes. Different agents expose different UIs, terminals, APIs, and sandbox models. The pack therefore separates three concerns:

1. Task definition
2. Result capture
3. Scoring and comparison

## Files

- `scripts/evals/agent_comparison_pack.json`: the canonical pack definition, task list, budgets, and metric weights.
- `scripts/score_agent_eval_pack.py`: CLI for generating a blank results template and scoring one or more completed result files.
- `backend/evaluation/agent_eval_pack.py`: reusable scoring logic used by the CLI and unit tests.

## Task Philosophy

The pack mixes six task shapes because top-tier coding agents fail in different ways:

- Localized bug-fix discipline
- Feature implementation with executable validation
- Refactor quality under minimal-diff pressure
- Read-only analysis quality
- Recovery quality after tool/runtime failure
- Multi-file change discipline across code, tests, and docs

This is intentional. Aider can look excellent on small edit loops and worse on broad orchestration. OpenHands may recover well under sandboxed execution but lose points on prompt economy. Claude Code may be fluid and fast but still needs to prove validation rigor. Grinta should score well on completion integrity and honest validation; this pack makes that visible instead of anecdotal.

## Result Capture Format

Each agent run is recorded as one JSON file with this shape:

```json
{
  "agent_id": "grinta",
  "pack_id": "top_tier_agent_comparison",
  "pack_version": "2026-04-24",
  "metadata": {
    "model": "openai/gpt-4o-mini",
    "run_date": "2026-04-24",
    "operator": "local",
    "notes": ""
  },
  "runs": [
    {
      "task_id": "bugfix_small_validation",
      "success": true,
      "verification_score": 5,
      "instruction_adherence_score": 4,
      "tool_discipline_score": 4,
      "code_quality_score": 4,
      "recovery_score": null,
      "turn_count": 8,
      "latency_seconds": 74.5,
      "cost_usd": 0.62,
      "notes": "Used focused pytest verification.",
      "evidence": [
        "pytest backend/tests/unit/foo.py -q",
        "diff stayed in one module"
      ]
    }
  ]
}
```

The 0-5 fields are deliberately compact. They are meant to be judged from transcript evidence, not guessed.

## Scoring Rules

- `success` is the dominant metric.
- Verification quality is weighted heavily because many agents still claim completion without adequate checks.
- Tool discipline and instruction adherence matter because top agents differ sharply in how much collateral damage they cause.
- Recovery only counts on tasks that actually require recovery.
- Turn, latency, and cost overruns apply bounded penalties instead of replacing quality metrics.

## Usage

Generate a blank template for one agent:

```bash
uv run python scripts/score_agent_eval_pack.py \
  --pack scripts/evals/agent_comparison_pack.json \
  --write-template grinta scripts/evals/grinta_results.json
```

Score multiple agents into one leaderboard:

```bash
uv run python scripts/score_agent_eval_pack.py \
  --pack scripts/evals/agent_comparison_pack.json \
  scripts/evals/grinta_results.json \
  scripts/evals/claude_code_results.json \
  scripts/evals/aider_results.json
```

JSON output is also supported:

```bash
uv run python scripts/score_agent_eval_pack.py \
  --pack scripts/evals/agent_comparison_pack.json \
  --format json \
  scripts/evals/grinta_results.json
```

## What This Still Does Not Solve

- It does not standardize each vendor's runtime policy.
- It does not eliminate evaluator bias in the 0-5 sub-scores.
- It does not automate external proprietary agents from inside this repo.

What it does do is force the comparison to be explicit, repeatable, and artifact-backed.