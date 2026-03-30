---
name: agent_memory
type: knowledge
version: 3.0.0
agent: Orchestrator
triggers:
  - /remember
---

# Long-lived project memory

**Tool choice** (note / working_memory / semantic_recall) is defined in the system prompt — use that; this playbook only covers **file-based lessons**.

## `lessons.md` (project lessons)

**Paths:** `.app/lessons.md` or `memories/repo/lessons.md`  
**Use for:** Durable repo facts — build/test commands, conventions, verified “we fixed X by Y”, architecture notes.  
**Do not use for:** Secrets, one-off tickets, user prefs, temporary hacks.

**Debug tier:** Richer `lessons.md` content may appear in system prompt when the session is in debug tier — keep entries concise.

## Vector / semantic recall

Past turns and fuzzy “what did we decide about X?” → use **`memory_manager`(semantic_recall)** per system prompt. No manual indexing step.

## `/remember` workflow

1. Summarize what to persist (bullets).  
2. Confirm with user if the write is large or overwrites a section.  
3. Append or edit `lessons.md` in small, titled sections; prefer one-liners for commands.
