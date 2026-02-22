---
name: agent_memory
type: knowledge
version: 2.0.0
agent: Orchestrator
triggers:
  - /remember
  - repository memory
  - repo memory
---

# Agent Memory System

Two complementary memory systems:

## 1. Repository Memory (lessons.md)

**Location:** `.Forge/lessons.md` or `memories/repo/lessons.md`

**Purpose:** Project-specific knowledge and historical lessons (automated/manual)

**What to store:**
- Repository structure & architecture
- Common commands (build, test, deploy)
- Code style & conventions
- Past mistakes and their verified fixes
- Development workflows
- Setup instructions

**What NOT to store:**
- Issue-specific info
- Temporary workarounds
- User preferences
- Secrets

**Auto-loads** at the start of every session (injected into system prompt).

## 2. Vector Memory (Automatic)

**Location:** Backend (ChromaDB/Qdrant)

**Purpose:** Semantic search across all conversations

**What's stored automatically:**
- User requests & questions
- Your responses & actions
- Code changes
- Decisions & rationale
- Error resolutions

**Performance:**
- ~110ms first query, ~35ms cached
- 92% accuracy
- Hybrid retrieval (vector + BM25 + re-ranking)

## When to Use Each

| Scenario | lessons.md | Vector Memory |
|----------|------------|---------------|
| Project commands | ✅ | Auto-captured |
| Code style | ✅ | Auto-captured |
| Bug we fixed | ✅ (Major) | ✅ |
| Past conversation | ❌ | ✅ |
| Team conventions | ✅ | Auto-captured |

**Golden rule:** General project knowledge + historical lessons → lessons.md. Everything else → vector memory (automated).

## Example: Save to lessons.md

**User:** "/remember the build process"

**You:**
```
I'll save to lessons.md:

1. Build: npm run build
2. Test: npm test -- --coverage
3. Lint: npm run lint
4. Pre-commit: Husky (lint + tests)

Save all or skip any?
```

After approval → Update `.Forge/lessons.md` or `memories/repo/lessons.md`.

## Best Practices

**lessons.md:**
- Concise (one-liners for commands)
- Focus on "What NOT to do" (mistakes avoid)
- Organized sections
- Current info only

**Vector Memory:**
- No action needed (automatic)
- Trust the system
- Reference past: "Similar to yesterday"
