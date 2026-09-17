---
name: agent_memory
type: knowledge
version: 3.0.0
agent: Orchestrator
triggers:
  - /remember
---

# Long-lived project memory

**Tool choice** (`memory` actions: working / persist; `search_history` for earlier turns) is defined in the system prompt — use that; this playbook covers **file-based lessons** and `/remember`.

## `lessons.md` (project lessons)

**Paths:** `.grinta/lessons.md` or `memories/repo/lessons.md`
**Use for:** Durable repo facts — build/test commands, conventions, verified “we fixed X by Y”, architecture notes.
**Do not use for:** Secrets, one-off tickets, user prefs, temporary hacks.

**Debug tier:** Richer `lessons.md` content may appear in system prompt when the session is in debug tier — keep entries concise.

## Searching earlier turns

Past turns that fell out of the visible window → use **`search_history(query="...")`** when it is in your tool list.

It is keyword search, not semantic: query with exact terms from the text you need (function names, file paths, error messages, command names). “parse_config KeyError” finds far more than “what went wrong with config loading?”.

## `/remember` workflow

1. Summarize what to persist (bullets).
2. Confirm with user if the write is large or overwrites a section.
3. Append or edit `lessons.md` in small, titled sections; prefer one-liners for commands.
