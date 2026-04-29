# Architecture Decision Records (ADRs)

This document records the key architectural decisions made in the Grinta project,
their context, and rationale.

---

## ADR-001: Event Sourcing for Session State

**Status:** Accepted  
**Date:** 2024-12  
**Context:** Agent sessions involve sequences of actions and observations that
must survive process crashes, support replay for debugging, and enable audit
trails.

**Decision:** Use event sourcing as the primary persistence model. All agent
actions and observations are immutable events appended to an `EventStream`.
Session state is reconstructed by replaying events.

**Consequences:**
- ✅ Full session replay from any point
- ✅ Crash recovery via Write-Ahead Log (WAL)
- ✅ Natural audit trail for every agent action
- ✅ Enables time-travel debugging
- ⚠️ Higher storage than CRUD (mitigated by condensation)
- ⚠️ Reconstruction cost grows with session length (mitigated by checkpoints)

---

## ADR-002: Write-Ahead Log (WAL) for Event Durability

**Status:** Accepted  
**Date:** 2024-12  
**Context:** Events must not be lost even if the process crashes mid-write.

**Decision:** Write a `.pending` marker file *before* persisting the event.
On startup, scan for pending markers and replay incomplete writes.

**Consequences:**
- ✅ Zero event loss guarantee on crash
- ✅ Simple implementation (no external dependencies)
- ⚠️ Slightly slower writes (two filesystem operations per event)

---

## ADR-003: Backpressure in EventStream

**Status:** Accepted  
**Date:** 2024-12  
**Context:** Under heavy load, subscriber queues could grow unbounded, leading
to OOM. Slow subscribers should not block fast producers.

**Decision:** Implement bounded subscriber queues with a configurable
high-water mark (HWM). When the queue is full, apply a configurable policy
(drop oldest or slow the producer).

**Consequences:**
- ✅ Prevents OOM under load
- ✅ Configurable per subscriber
- ⚠️ Events may be dropped for slow subscribers (drop policy)

---

## ADR-004: 21-Service Orchestration Decomposition

**Status:** Accepted  
**Date:** 2025-01  
**Context:** `SessionOrchestrator` grew to 2000+ LOC with mixed responsibilities:
state management, error recovery, safety checks, budget enforcement, stuck
detection, and more.

**Decision:** Decompose into 21 focused services, each under 200 LOC, sharing
state through an `OrchestrationContext` facade. The session orchestrator coordinates service
calls but delegates logic.

**Consequences:**
- ✅ Each service is independently testable
- ✅ Single responsibility per service
- ✅ Controller LOC reduced from 2000+ to ~870
- ⚠️ More files to navigate (mitigated by clear naming)
- ⚠️ OrchestrationContext coupling (mitigated by interface discipline)

---

## ADR-005: Circuit Breaker Pattern for Agent Safety

**Status:** Accepted  
**Date:** 2025-01  
**Context:** Autonomous agents can enter failure loops, executing the same
failing action repeatedly, accumulating cost without progress.

**Decision:** Implement a circuit breaker that trips after configurable
thresholds: consecutive errors (5), stuck detections (3), or high-risk
actions (10). When tripped, the agent pauses and requires user intervention.

**Consequences:**
- ✅ Prevents runaway cost
- ✅ Protects against infinite loops
- ✅ User retains control
- ⚠️ May pause prematurely on legitimate retry sequences

---

## ADR-006: Six-Strategy Stuck Detection

**Status:** Accepted  
**Date:** 2025-01  
**Context:** Simple "same action repeated N times" detection misses subtle
stuck patterns like semantic loops or oscillating action-observation pairs.

**Decision:** Implement six complementary detection strategies:
1. Repeating identical actions
2. Repeating identical errors
3. Monologue loops (thinking without acting)
4. Action-observation oscillation patterns
5. Semantic loops (similar but not identical actions)
6. Context window error loops

**Consequences:**
- ✅ Catches subtle stuck patterns
- ✅ Each strategy independently tunable
- ⚠️ More complex than simple repetition check

---

## ADR-007: Multiple Compactor Strategies

**Status:** Accepted  
**Date:** 2025-02  
**Context:** Long agent sessions exceed LLM context windows. Different
session types need different compression strategies — code-heavy sessions
benefit from observation masking, while research sessions need semantic
filtering.

**Decision:** Implement 8 compactor strategies behind a common interface,
with a `smart` default that adapts automatically. Users can select and
configure compactors per agent. The current code/config surface may still use
`condenser` during the migration window.

**Compactors:** smart, observation_masking, recent, amortized,
structured_summary, no_op, pipeline, auto.

**Consequences:**
- ✅ Optimal strategy for each use case
- ✅ Pipeline compactor allows chaining
- ✅ Smart default requires no configuration
- ⚠️ 8 implementations to maintain

---

## ADR-008: Socket.IO over Plain WebSocket

**Status:** Historical (legacy server phase)  
**Date:** 2024-12  
**Context:** Need real-time bidirectional communication between UI clients/frontend
and backend for streaming agent actions.

**Decision:** Use Socket.IO instead of raw WebSocket for its built-in:
- Automatic reconnection with backoff
- Room management for conversation isolation
- Event namespacing (typed events vs raw messages)
- Fallback to long-polling if WebSocket fails

**Consequences:**
- ✅ Robust reconnection out of the box
- ✅ Clean event-based API
- ✅ Room-based message routing
- ⚠️ Additional library dependency
- ⚠️ Not compatible with plain WebSocket clients

**Note (current state):** Grinta is now CLI-first for primary usage. The raw HTTP action backend remains available for API/OpenAPI tooling, while real-time UI assumptions are no longer the default architecture anchor.

---

## ADR-009: Tree-Sitter for Structure-Aware Editing

**Status:** Accepted  
**Date:** 2025-01  
**Context:** Plain text find-and-replace edits are fragile and language-
unaware. Edits that cross structural boundaries (functions, classes) produce
broken code.

**Decision:** Use Tree-sitter parsing across 45+ languages to understand
code structure before applying edits. The structure editor validates that
edits respect syntactic boundaries.

**Consequences:**
- ✅ Edits that respect language structure
- ✅ 45+ language support via Tree-sitter grammars
- ✅ Better error detection before applying changes
- ⚠️ Tree-sitter grammar maintenance burden
- ⚠️ Parse time overhead (mitigated by caching)

---

## ADR-010: JSON Settings as Default Local Config Surface

**Status:** Superseded (legacy TOML-first decision replaced)  
**Date:** 2024-12  
**Context:** Early builds used TOML-heavy examples and guidance, which diverged
from the actual local onboarding path and created user confusion.

**Decision (current):** Use `settings.json` as the default user-facing local
configuration surface: `~/.grinta/settings.json` for installed CLI runs,
repository `settings.json` for source checkouts, and `APP_ROOT` as an explicit
override. Environment variables remain supported for secrets, overrides, and
automation.

**Consequences:**
- ✅ Onboarding is simpler and consistent with starter templates
- ✅ LLM-facing tooling and scripts can read/write one familiar format
- ✅ Environment-based secret handling remains available
- ⚠️ Advanced nested tuning still requires deeper config knowledge

---

## ADR-011: Local-First Architecture

**Status:** Accepted  
**Date:** 2024-12  
**Context:** Users of an AI coding agent handle proprietary source code.
Sending code to cloud services raises privacy and security concerns.

**Decision:** Run entirely locally by default. The agent, runtime, and all
storage are local. Only LLM API calls leave the machine (and Ollama
eliminates even that).

**Consequences:**
- ✅ Complete privacy — code never leaves the machine
- ✅ Works offline with Ollama
- ✅ No cloud infrastructure required
- ⚠️ Limited by local compute resources
- ⚠️ No built-in collaboration features

---

## ADR-012: Pydantic for Configuration and Schema Validation

**Status:** Accepted  
**Date:** 2024-12  
**Context:** Configuration and data schemas need runtime validation, clear
error messages, and serialization support.

**Decision:** Use Pydantic v2 for all configuration models, event schemas,
and API request/response models.

**Consequences:**
- ✅ Runtime validation with clear error messages
- ✅ Automatic JSON serialization
- ✅ IDE support via type annotations
- ✅ Consistent validation across all layers
- ⚠️ Pydantic v2 migration complexity
- ⚠️ Performance overhead for hot paths (mitigated by caching)

---

## ADR-013: MCP Integration for External Tools

**Status:** Accepted  
**Date:** 2025-06  
**Context:** The agent ecosystem is moving toward the Model Context Protocol
(MCP) as a standard for tool integration. Supporting MCP allows Grinta to
leverage a growing ecosystem of tool servers.

**Decision:** Implement MCP client support with cached wrapper tools.
MCP servers are configured through current config surfaces (`settings.json` and
environment-backed config loading) and their tools appear
alongside built-in tools.

**Consequences:**
- ✅ Access to growing MCP tool ecosystem
- ✅ Standard protocol (future-proof)
- ✅ Clean separation: tool servers are external processes
- ⚠️ Additional complexity in tool resolution
- ⚠️ External process management overhead

---

## ADR-014: FastAPI for the Server Layer

**Status:** Accepted  
**Date:** 2024-12  
**Context:** Need a high-performance async HTTP framework that integrates
well with ASGI middleware patterns and provides automatic API documentation.

**Decision:** Use FastAPI with Uvicorn ASGI server.

**Consequences:**
- ✅ Native async/await support
- ✅ Automatic OpenAPI documentation
- ✅ Pydantic integration for validation
- ✅ High performance (ASGI)
- ⚠️ Middleware ordering is order-sensitive

---

## ADR-015: Textual TUI over Web Frontend

**Status:** Superseded — Grinta is CLI-first in current local workflows. The
Python package **`client`** remains for tests and automation.

**Date:** 2025-01 (superseded 2026-03)  
**Context:** Developers using a coding agent likely prefer a terminal-native
interface over a browser-based one. A TUI avoids Node.js dependencies and
integrates naturally into terminal workflows.

**Decision (historical):** Build the primary UI as a Textual TUI. A web frontend existed
as an alternative during that phase.

**Consequences (historical):**
- ✅ Zero Node.js/browser dependency for TUI users
- ✅ Native terminal integration
- ✅ Keyboard-driven workflow
- ⚠️ Limited to terminal capabilities (no rich media)
- ⚠️ Textual framework learning curve

---

## ADR-016: Grinta Vocabulary Contract

**Status:** Accepted  
**Date:** 2026-03  
**Context:** Grinta has evolved far beyond its original shell, but parts of its
top-level language still undersell what the system actually is. The strongest
Grinta characteristics are durable run history, governed execution, adaptive
context management, and local-first runtime control. Without a canonical
vocabulary, future renames will drift, public docs will stay inconsistent, and
the codebase will keep reading more inherited than it really is.

**Decision:** Standardize on a Grinta-first vocabulary contract and use it as
the reference language for future documentation, public protocols, package
decisions, and code symbol migration. This vocabulary lock should be set before
any large implementation-planning pass or rename wave.

`Outcome` is preferred over `Result` or `Effect` because it fits ledger
semantics cleanly without implying that only world-state mutations matter.

**Canonical terms (current):**

- Keep clear baseline terms: `Action`, `Observation`, `Event`, `State`, `Runtime`
- Keep `Compactor` as the canonical context-compression term
- Use `SessionOrchestrator` for orchestrator-level control language in docs
- Use `ExecutionPolicy` as conceptual language while code may still reference autonomy

**Terms intentionally preserved:**

- `Agent`
- `Runtime`
- `Playbook`
- `Tool`
- `Conversation` on user-facing surfaces
- `Core`, `Security`, `Telemetry`, `Validation`, `Utils`

**Naming principles:**

- Use industrial, precise names; avoid cute or mystical metaphors.
- Name concepts by semantic role, not implementation detail.
- Keep the architecture model-agnostic and OS-agnostic; avoid provider-specific or platform-specific core nouns.
- Lock the language before large implementation planning or rename waves.
- Change the inherited conceptual shell first, not the strong mechanisms underneath it.

**Consequences:**

- ✅ Grinta now has one explicit language contract for future renames
- ✅ Implementation planning can evaluate changes against one stable vocabulary lock
- ✅ Documentation can describe Grinta in terms that match its actual strengths
- ✅ Package and protocol changes can be evaluated against one stable reference
- ⚠️ During transition, docs may reference both canonical names and current code names
- ⚠️ A later implementation sweep must migrate symbols, packages, and persisted schemas carefully

---

## ADR-017: Non-Code Document Edit Protocol

**Status:** Accepted  
**Date:** 2026-04  
**Context:** Tree-sitter provides strong structure-aware edits for source code, but non-code artifacts (markdown, config, docs) are fragile when edited only through raw `old_str`/`new_str` matching.

**Decision:** Standardize a document-edit protocol for non-code files with explicit edit modes:
- `format` for parser-based mutations of structured formats (JSON/YAML/TOML)
- `section` for anchor-bounded edits
- `range` for deterministic line-range edits with optional hash guards
- `patch` for strict-context unified-diff hunk application
- `replace` retained only as backward-compatible fallback

**Consequences:**
- ✅ Deterministic edits with stronger constraints than raw substring replacement
- ✅ Better behavior under text drift and repeated phrases
- ✅ Clear failure modes for ambiguous anchors/hunks
- ✅ `replace_text`, `view_and_replace`, and `batch_replace` removed from tool surface; prefer `ast_code_editor`, `edit_mode`, and sequential edits + checkpoints for multi-file work
- ⚠️ More implementation complexity in file-editor runtime
- ⚠️ Additional parser dependency risk for YAML/TOML paths
