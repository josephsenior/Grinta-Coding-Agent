# Forge Vocabulary

This document defines the canonical Forge architecture language.

The codebase still contains older implementation names. This document is the
reference contract for future renames across docs, protocols, package
decisions, and code symbols.

This canonical set is the vocabulary lock to use before implementation
planning. If it changes, update this document and ADR-016 first.

## Principles

- Use industrial, precise names rather than cute or mystical metaphors.
- Name concepts by semantic role, not implementation detail.
- Keep the vocabulary model-agnostic and OS-agnostic.
- Preserve concepts that are already clear and broadly understood.
- Lock the language before large implementation planning or rename waves.
- Change the inherited conceptual shell first, not the strong mechanisms underneath it.

## Canonical Terms

| Current code term | Canonical Forge term | Notes |
| --- | --- | --- |
| `Agent` | `Agent` | Keep |
| `AgentController` / bare `Controller` | `SessionOrchestrator` | Central control-plane component |
| `Action` | `Operation` | Intent emitted by the agent or client |
| `Observation` | `Outcome` | Chosen over `Result` or `Effect` because it fits ledger semantics without implying mutation only |
| `Event` | `Record` | Envelope concept spanning operations and outcomes |
| `EventStream` | `Ledger` | Durable ordered record flow |
| `EventStore` | `LedgerStore` | Persistence backend for ledger records |
| backend `Session` | `Run` | Internal execution unit |
| user-facing `Conversation` | `Conversation` | Keep on product surfaces |
| `State` | `RunState` | Internal execution state |
| `Checkpoint` | `Snapshot` | Persisted run-state capture |
| `Trajectory` | `Transcript` | Exported or replayed record history |
| `ActionExecutor` | `RuntimeExecutor` | Runtime-side execution entry point |
| `PendingAction` | `OpenOperation` | In-flight operation awaiting an outcome |
| `Autonomy` | `ExecutionPolicy` | Degree of review, confirmation, and governance |
| `Condenser` | `Compactor` | Context compression mechanism |
| `ConversationMemory` / generic memory layer | `ContextMemory` | Run-scoped context management layer |
| `ToolInvocationPipeline` | `OperationPipeline` | Validation and execution pipeline |
| `Review` | `Governance` | Critique and guardrail layer |

## Terms Intentionally Preserved

These terms are already clear and should not be renamed for distinctness alone.

- `Agent`
- `Runtime`
- `Playbook`
- `Tool`
- `Conversation` on user-facing surfaces
- `Core`
- `Security`
- `Telemetry`
- `Validation`
- `Utils`

## Terms To Avoid

Avoid these naming patterns in future work:

- Metaphor-heavy names like `cognition`, `perception`, `scrutiny`, `chronicle`, `anvil`, `workshop`
- Overloaded bare names like `controller`
- ML-jargon like `trajectory`
- Ambiguous infra nouns like bare `session` and bare `memory`
- Provider-specific or OS-specific core concepts

## Implementation Package Notes

Canonical vocabulary and package layout are related, but they are not the same
contract. The current implementation package state is:

| Legacy package | Current package | Notes |
| --- | --- |
| `backend/controller` | `backend/orchestration` | Aligns with `SessionOrchestrator` |
| `backend/events` | `backend/ledger` | Aligns with `Ledger` |
| `backend/api` | `backend/gateway` | Gateway terminology is stable |
| `backend/storage` | `backend/persistence` | Persistence terminology is stable |
| `backend/memory` | `backend/context` | Supports `ContextMemory` language |
| `backend/review` | `backend/governance` | Aligns with `Governance` |
| `backend/llm` | `backend/inference` | Distinct model/provider layer |
| `backend/knowledge_base` | `backend/knowledge` | Shorter stable term |
| `backend/playbook_engine` | `backend/playbooks/engine` | Preserves `Playbook` while separating engine internals |
| `backend/adapters` | `backend/gateway/adapters` | Gateway-scoped integration surface |
| `backend/mcp_client` | `backend/gateway/integrations/mcp` | Gateway integration surface |
| `backend/cli` | `backend/gateway/cli` | Gateway-facing CLI surface |
| `backend/runtime` | `backend/execution` | Current package path; the canonical system term remains `Runtime` |
| `backend/engines/orchestrator` | `backend/engine` | Current engine package shape; the locked vocabulary does not introduce `reasoning` |

## Transition Rule

Until the migration lands:

- Docs should use the canonical Forge term first.
- Current code names can appear in backticks for orientation.
- When prose and package paths differ, use the canonical term in prose and the actual package path in backticks.
- New symbols, docs, and public contracts should prefer the canonical term unless a migration constraint blocks it.
