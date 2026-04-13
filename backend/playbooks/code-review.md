---
name: code_review
type: knowledge
version: 4.0.0
agent: Orchestrator
triggers:
  - /codereview
  - /codereview-roasted
---

# Code review (PR/MR)

Use provider MCP tools when available, or provider API with `GIT_PROVIDER_TOKEN` (or provider-specific token env vars). Never post secrets in comments.

## Workflow

1. Load PR/MR metadata and diff (or patches).
2. Review correctness, edge cases, readability, and tests.
3. Leave inline comments on specific lines when the API supports it.
4. Submit review: **APPROVE**, **REQUEST_CHANGES**, or **COMMENT**.

## Review modes

- `/codereview` (standard): balanced and collaborative. Prioritize correctness and missing tests.
- `/codereview-roasted` (critical): direct and architecture-first. Prioritize bad abstractions, avoid style bikeshedding, and call out risky complexity.

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

## API usage

Post comments and submit the final review through provider REST when needed. Use the same auth header pattern used by your MCP setup. Prefer MCP when available to reduce URL and auth mistakes.

## Review lens

- **Risk:** authz, injection (SQL/XSS), unsafe deserialization, resource limits.
- **Quality:** error handling, null/empty cases, naming, test coverage for new logic.
