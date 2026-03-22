---
name: React
type: knowledge
version: 2.0.0
agent: Orchestrator
triggers:
  - /react
---

# React / hooks focus

Use when the user invokes **`/react`**.

## State

- Prefer **functional updates** `setX(p => …)` when next state depends on previous.
- Group related fields in **one object** instead of many scalars when they change together.
- **Derive** values with plain expressions when possible — no `useState` for computable data.

## Effects

- List **all** reactive values in the dependency array ESLint expects.
- **Clean up** subscriptions, timers, and listeners in the effect return.
- Do not use effects to mirror state you can compute during render.

## Lists & keys

Use **stable ids** (`item.id`), never array index, for dynamic lists.

## Immutability

Update arrays/objects with spreads / `map` / `filter` — never mutate existing state in place.

## Performance (when needed)

`useMemo` / `useCallback` / `React.memo` only after measurement or clear prop-stability needs — avoid by default.

## Composition

Prefer **children** or context over deep prop drilling for cross-cutting UI state.
