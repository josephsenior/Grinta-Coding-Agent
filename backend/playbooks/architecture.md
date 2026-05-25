---
name: architecture
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /architecture
  - /adr
---

# Architecture and ADR workflow

Use when a change has non-trivial tradeoffs across reliability, cost, velocity, or team ownership.

## 1) Frame the decision

- Write one sentence each for: objective, constraints, and non-goals.
- Identify the bounded context touched (API, data model, jobs, UI, infra).
- Declare what must remain stable (contracts, latency SLO, rollout risk).

## 2) Enumerate options

For each option include:
- Scope of change and blast radius.
- Migration complexity and rollback path.
- Operational cost (runtime + maintenance burden).
- Failure modes and observability requirements.

Keep at least two viable options before converging.

## 3) Select with explicit criteria

Rank options on:
- Time-to-safe-delivery.
- Long-term maintainability.
- Performance and cost profile.
- Security and compliance fit.

Prefer the option that minimizes irreversible coupling unless a clear product deadline requires otherwise.

## 4) Ship in phases

- Phase 1: compatibility layer / adapter.
- Phase 2: dual-read or shadow validation when data paths change.
- Phase 3: cutover behind a flag.
- Phase 4: cleanup and dead-code removal.

## 5) ADR output

Produce a short ADR section:
- Context
- Decision
- Consequences (positive + negative)
- Rollout plan
- Rollback plan

## Minimal example prompt

`/architecture: redesign event ingestion from sync HTTP writes to async queue + workers with idempotency keys`

