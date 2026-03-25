---
name: add_agent
type: knowledge
version: 2.0.0
agent: Orchestrator
triggers:
  - /add_agent
---

# Adding a playbook

**Full policy and inventory:** `backend/playbooks/README.md` in this repo.

**Rules:** Slash-first triggers; no duplication of orchestrator system prompt (security, tool discipline, memory tool matrix). Keep one workflow per file; &lt; ~100 lines; examples &gt; prose.

**User / repo playbooks:** `~/.Forge/playbooks/*.md` or ship under `backend/playbooks/` with a PR.

```markdown
---
name: example
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /example
---

# Example

## Checklist
1. ...
2. ...

## Minimal snippet
...
```
