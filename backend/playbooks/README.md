# Playbooks

**Purpose:** On-demand procedural and domain guidance. They inject only when a **recall/knowledge** query matches a trigger (see `Memory._find_playbook_knowledge`).

**Not here:** General agent behaviour, tool frugality, security rules, memory-tool choice, or error-recovery for shell — that lives in the orchestrator **system prompt** (`backend/engine/prompts/`). Do not duplicate it in playbooks.

## Trigger policy (quality / focus)

1. **Prefer slash commands** (`/debug`, `/feature`, …) so playbooks fire when the user *asks* for that mode, not on every substring mention (`pytest`, `ssh`, `fastapi` in normal chat caused noisy injections).
2. **Optional second triggers** only when they are **long, distinctive phrases** (not single common words).
3. **Target &lt; ~100 lines** per playbook; examples over rules; one clear workflow per file.

## Locations

| Source | Path |
|--------|------|
| Global (shipped) | This directory |
| Per-user | `~/.app/playbooks/` |
| Per-repo | `.app/playbooks/repo.md` (auto context; different loader) |

## Inventory (global)

| File | Intent |
|------|--------|
| `add_agent.md` | How to add a playbook (meta) |
| `add_repo_inst.md` | Scaffold `.app/playbooks/repo.md` |
| `address_pr_comments.md` | `/address_pr_comments` workflow |
| `agent_memory.md` | `/remember` — lessons.md vs vector recall |
| `api.md` | `/api` — REST/FastAPI patterns |
| `code-review.md` | `/codereview` |
| `codereview-roasted.md` | `/codereview-roasted` |
| `database.md` | `/database` |
| `debug.md` | `/debug` |
| `documentation.md` | `/docs` |
| `feature.md` | `/feature` |
| `react.md` | `/react` |
| `refactoring.md` | `/refactor` |
| `ssh.md` | `/ssh` |
| `testing.md` | `/testing` |
| `update_pr_description.md` | `/update_pr_description` |
| `update_test.md` | `/update_test` |

## Authoring template

```markdown
---
name: my_playbook
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /my_playbook
---

# Title

One paragraph: what this playbook is for.

## Steps or checklist
...

## One minimal example
...
```
