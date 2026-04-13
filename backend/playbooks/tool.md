---
name: tool
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /tool
---

# Tool authoring and integration

Use this when adding or improving agent tools and MCP-connected capabilities.

## 1) Define the tool contract

- Name, purpose, inputs, and expected output shape.
- Failure modes and safe fallback behavior.
- Decide whether the tool is local code, MCP-backed, or both.

## 2) Implement minimal reliable behavior

- Start with a narrow command path that solves one concrete use case.
- Validate input early and return clear error messages.
- Keep tool output structured and compact.

## 3) Wire integration points

- Register tool where runtime can discover it.
- Ensure playbook and prompt guidance reference the same capability name.
- Add one usage path in docs for contributors.

## 4) Add tests and negative cases

- Happy path test with realistic input.
- One malformed input test.
- One dependency failure test (network/file/system).

## 5) Verify in workflow

- Run targeted tests for the tool and integration layer.
- Confirm behavior through one end-to-end scenario.

## Example: MCP-focused validation commands

```bash
uv run pytest backend/tests/unit/playbooks -q
uv run pytest backend/tests/unit/integrations -q
```

Adjust paths to the exact tool module and integration boundary you changed.
