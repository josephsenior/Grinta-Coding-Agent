# Playbooks

**Purpose:** On-demand procedural and domain guidance. They inject only when a **recall/knowledge** query matches a trigger (see `Memory._find_playbook_knowledge`).

**Not here:** General agent behaviour, tool frugality, security rules, memory-tool choice, or error-recovery for shell — that lives in the orchestrator **system prompt** (`backend/engine/prompts/`). Do not duplicate it in playbooks.

## Trigger policy (quality / focus)

1. **Prefer slash commands** (`/debug`, `/feature`, …) so playbooks fire when the user *asks* for that mode, not on every substring mention (`pytest`, `fastapi`, and other short generic terms can cause noisy injections).
2. **Optional second triggers** only when they are **long, distinctive phrases** (not single common words).
3. **Target &lt; ~100 lines** per playbook; examples over rules; one clear workflow per file.
4. **Auto-trigger is disabled by default for now.** Non-slash triggers only run if `GRINTA_ENABLE_PLAYBOOK_AUTO_TRIGGER=1` is set.

## Locations

| Source | Path |
| ------ | ---- |
| Global (shipped) | This directory |
| Per-user | `~/.grinta/playbooks/` |
| Per-repo | `.grinta/playbooks/repo.md` (auto context; different loader) |

## Inventory (global)

| File | Intent |
| ---- | ------ |
| `add_repo_inst.md` | Scaffold `.grinta/playbooks/repo.md` |
| `address_pr_comments.md` | `/address_pr_comments` workflow |
| `agent_memory.md` | `/remember` — lessons.md vs vector recall |
| `api.md` | `/api` — REST/FastAPI/Express patterns |
| `code-review.md` | `/codereview` and `/codereview-roasted` |
| `database.md` | `/database` |
| `debug.md` | `/debug` |
| `deps.md` | `/deps` and `/dependencies` — add, upgrade, audit dependencies |
| `documentation.md` | `/docs` |
| `feature.md` | `/feature` |
| `git-wizard.md` | `/git` — commit surgery, rebase, bisect, reflog salvage |
| `incident.md` | `/incident` and `/oncall` — live issue triage and recovery |
| `log-fu.md` | `/logs` and `/json` — log/JSON analysis with rg and jq |
| `migration.md` | `/migration` and `/upgrade` — staged upgrade workflow |
| `net-diag.md` | `/net` and `/network` — DNS, TLS, HTTP, connectivity diagnostics |
| `perf.md` | `/perf` and `/profile` — measure-first performance profiling |
| `python.md` | `/python` and `/py` |
| `react.md` | `/react` |
| `refactoring.md` | `/refactor` |
| `shell.md` | `/shell` and `/bash` — non-interactive terminal execution |
| `testing.md` | `/testing` |
| `tool.md` | `/tool` — tool authoring and MCP integration |
| `typescript.md` | `/typescript` and `/ts` — TypeScript code generation rules |
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
