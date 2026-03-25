---
name: code_review
type: knowledge
version: 3.0.0
agent: Orchestrator
triggers:
  - /codereview
---

# Code review (PR/MR)

Use provider **MCP tools** or API with `GIT_PROVIDER_TOKEN` (or provider-specific env). Follow workspace **SECURITY** — never post secrets in comments.

## Workflow

1. Load PR/MR metadata and **diff** (or patches).  
2. Review: correctness, edge cases, readability, tests.  
3. Leave inline comments on specific lines when the API supports it.  
4. Submit review: **APPROVE**, **REQUEST_CHANGES**, or **COMMENT**.

## Comment template

```markdown
## Summary
Briefly what changed.

**Must fix**
- …

**Suggestions**
- …

**Nice**
- …
```

## API examples (adjust host/path to provider)

Post comment / submit review via provider REST; use the same auth header pattern your MCP tools use. Prefer **MCP** when available — fewer raw URL mistakes.

## Review lens

- **Risk:** authz, injection (SQL/XSS), unsafe deserialization, resource limits.  
- **Quality:** error handling, null/empty cases, naming, test coverage for new logic.
