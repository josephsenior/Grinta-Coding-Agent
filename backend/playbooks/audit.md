---
name: audit
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /audit
---

# Session audit workflow

Use this to audit what happened in a session and explain why decisions were made.

## 1) Define audit scope

- Timebox the window or select specific failing interactions.
- Choose one objective: correctness, safety, or process drift.

## 2) Build a minimal timeline

- Collect key user intents, actions executed, and resulting observations.
- Highlight first divergence from expected behavior.
- Record whether divergence was due to logic, tooling, or missing context.

## 3) Validate decision quality

- Check if each major step had enough evidence.
- Flag where assumptions were made without verification.
- Separate confirmed facts from inferred explanations.

## 4) Produce audit findings

- Root cause in one sentence.
- One must-fix item and one prevention item.
- Include verification command(s) tied to the finding.

## 5) Store durable lessons

- Persist stable lessons to repository memory.
- Keep entries short and actionable.

## Example: audit output checklist

```text
- Scope: Playbook loading regression in current branch
- Root cause: Trigger overlap created unintended recall
- Must-fix: tighten trigger phrase for new playbook
- Prevention: add regression test for trigger ambiguity
- Verify: uv run pytest backend/tests/unit/playbooks/engine/test_playbook_match_trigger.py -q
```
