# Grinta Vocabulary

This document defines the canonical Grinta architecture language and tracks
the migration status of each term. It serves as both reference contract and
implementation status tracker.

## Principles

- Use industrial, precise names rather than cute or mystical metaphors.
- Name concepts by semantic role, not implementation detail.
- Keep the vocabulary model-agnostic and OS-agnostic.
- Preserve concepts that are already clear and broadly understood.

## Canonical Terms — Migration Status

| Code term | Canonical term | Status | Notes |
| --- | --- | --- | --- |
| `Agent` | `Agent` | ✅ Kept | No rename needed |
| `AgentController` | `SessionOrchestrator` | ✅ Complete | `backend/orchestration/session_orchestrator.py` |
| `Condenser` | `Compactor` | ✅ Complete | 40+ files use `Compactor` exclusively |
| `Review` | `Governance` | ✅ Complete | Package is `backend/governance/` |
| `Action` | `Action` | ✅ Kept | Rename to `Operation` deferred — term is clear and broadly understood |
| `Observation` | `Observation` | ✅ Kept | Rename to `Outcome` deferred — same rationale |
| `Event` | `Event` | ✅ Kept | Rename to `Record` deferred — foundational base class |
| `EventStream` | `EventStream` | ✅ Kept | Rename to `Ledger` deferred — the package is already `backend/ledger/` |
| `State` | `State` | ✅ Kept | Rename to `RunState` deferred — universally understood |
| `Checkpoint` | `Checkpoint` | ✅ Kept | Rename to `Snapshot` deferred — used across rollback and state layers |
| `Trajectory` | `Trajectory` | ✅ Kept | Rename to `Transcript` deferred — config and test integration deep |
| `ToolInvocationPipeline` | `ToolInvocationPipeline` | ✅ Kept | Rename to `OperationPipeline` deferred |
| `PendingAction` | `PendingAction` | ✅ Kept | Rename to `OpenOperation` deferred |
| `Autonomy` | `ExecutionPolicy` | 🔄 Conceptual | Docs use execution policy; code uses autonomy level |
| `ConversationMemory` | `ContextMemory` | 🔄 Conceptual | Package is `backend/context/`; class is `ContextMemoryManager` |

## Terms Intentionally Preserved

These terms are already clear and should not be renamed for distinctness alone.

- `Agent`, `Runtime`, `Playbook`, `Tool`
- `Conversation` on user-facing surfaces
- `Core`, `Security`, `Telemetry`, `Validation`, `Utils`
- `Action`, `Observation`, `Event`, `State`, `Checkpoint` — clear, broadly understood

## Terms To Avoid

- Metaphor-heavy names (`cognition`, `perception`, `scrutiny`, `chronicle`, `anvil`, `workshop`)
- Overloaded bare names (`controller`)
- ML-jargon (`trajectory` in new code — existing uses are grandfathered)
- Ambiguous infra nouns (bare `session`, bare `memory`)
- Provider-specific or OS-specific core concepts

## Package Layout

| Legacy package | Current package | Notes |
| --- | --- | --- |
| `backend/controller` | `backend/orchestration` | Aligns with `SessionOrchestrator` |
| `backend/events` | `backend/ledger` | Durable event stream and persistence |
| `backend/api` | `backend/gateway` | Gateway terminology is stable |
| `backend/storage` | `backend/persistence` | Persistence terminology is stable |
| `backend/memory` | `backend/context` | Context memory and compaction |
| `backend/review` | `backend/governance` | Critique and guardrail layer |
| `backend/llm` | `backend/inference` | Model and provider layer |
| `backend/knowledge_base` | `backend/knowledge` | Shorter stable term |
| `backend/playbook_engine` | `backend/playbooks/engine` | Playbook execution internals |
| `backend/runtime` | `backend/execution` | Canonical system term remains `Runtime` |
| `backend/engines/orchestrator` | `backend/engine` | Agent engine (planner, executor, memory, safety) |
