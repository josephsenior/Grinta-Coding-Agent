# Grinta Vocabulary

Canonical terminology for current Grinta docs and contributor communication.

## Principles

- Prefer clear engineering terms over metaphors.
- Prefer terms that map directly to current modules.
- Keep user-facing terms stable unless behavior changes.

## Core Terms

| Term | Meaning | Current Status |
| --- | --- | --- |
| Session orchestrator | Main control loop for a run | Active (`backend/orchestration`) |
| Action | Intended operation proposed by agent | Active (`backend/ledger/action`) |
| Observation | Result of an action | Active (`backend/ledger/observation`) |
| Event stream | Ordered flow/storage of runtime records | Active (`backend/ledger`) |
| Compactor | Context compression strategy | Active (`backend/context`) |
| Runtime executor | Local action execution engine | Active (`backend/execution`) |
| Execution policy | Safety/autonomy constraints for runtime behavior | Active (autonomy + security policy paths) |
| Task validation | Finish gate ensuring work is actually complete | Active (`task_validation_service`) |

## Terms Intentionally Kept

These are already clear and broadly understood in the codebase:

- `Action`
- `Observation`
- `Event`
- `State`
- `Runtime`
- `Playbook`
- `Tool`

## Package Vocabulary

| Package | Meaning |
| --- | --- |
| `backend/cli` | Terminal interface and command loop |
| `backend/context` | Memory and compaction |
| `backend/core` | Config, constants, shared foundations |
| `backend/engine` | Agent decision and prompt orchestration |
| `backend/execution` | Local runtime and raw action server |
| `backend/inference` | Model/provider routing and LLM clients |
| `backend/integrations` | External integration adapters |
| `backend/knowledge` | Retrieval and knowledge subsystems |
| `backend/ledger` | Actions, observations, event stream |
| `backend/orchestration` | Session orchestrator and services |
| `backend/persistence` | Durable storage and state persistence |
| `backend/playbooks` | Playbook assets and loaders |
| `backend/security` | Command risk analysis and policy checks |
| `backend/telemetry` | Lightweight instrumentation |
| `backend/tools` | Tool implementations |
| `backend/validation` | Validation and quality checks |

## Naming Guidance for New Code

Prefer:

- explicit names (`task_validation_service`, `event_router_service`)
- subsystem-aligned names (`inference`, `execution`, `orchestration`)
- behavior-based terms (`retry`, `recovery`, `safety`)

Avoid:

- renamed aliases that do not map to real modules
- metaphor-heavy names that hide responsibilities
- introducing parallel terms for the same concept
