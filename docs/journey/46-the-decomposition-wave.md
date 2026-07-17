# 46. The Decomposition Wave

> **Later update:** The seven-tool file API described during this wave changed
> again when `read_symbol` was removed. July also added public long-run evidence,
> orchestrator-owned project memory, durable task state, capability-driven prompt
> caching, a PowerShell-first native-Windows default, and broader CI gates. See
> [chapters 47](47-the-long-runs-and-their-receipts.md) and
> [48](48-the-continuity-contract.md).

Chapter 45 described the moment Grinta stopped feeling like an engine with a prompt
and started feeling like a tool someone could actually sit inside.

That chapter also named a problem it did not fully solve: once the product surface
became real, the remaining mess became *more visible*. Transcript cards, settings
dialogs, and session management all worked — but they sat on top of files that
had grown past the point where a single contributor could hold the whole shape in
working memory.

This chapter is about what happened next: the deliberate 8.1 → 9.0 improvement
plan, the second decomposition wave across CLI and backend, and the product
decisions that only became possible once the internals were legible enough to
change without fear.

---

## The Product Surface Created a Maintenance Debt

There is a cruel symmetry in mature solo projects.

The interface gets better first because users — including you, dogfooding at 2 AM —
feel pain immediately when startup is wrong or the HUD lies. The engine underneath
can stay swollen longer because it still *works* even when nobody wants to open
the files.

By mid-2026 the mismatch was obvious:

- `unified_renderer.py` had passed 1,400 lines.
- `_app_renderer_event_processor.py` was approaching 2,000.
- `config_manager.py`, `activity_card.py`, and `theme.py` were each doing the job
  of a small package while pretending to be one file.
- On the backend, `context_pipeline.py`, `canonical_state.py`, `llm.py`, and
  `_file_edits.py` had the same disease: correct behavior, frightening boundaries.

The product had become honest. The file tree had not.

So I stopped treating "we'll split it later" as a plan and wrote one down:
`docs/REFACTOR_BASELINE.md`, `docs/CLI_MODULE_MAP.md`, and
`backend/scripts/verify/check_file_size.py`. The goal was not elegance for its
own sake. The goal was **legibility under change** — the precondition for anyone
else (or future-me) to trust a diff.

---

## The 8.1 → 9.0 Plan in Plain Language

The improvement plan was organized in phases, each with a receipt:

| Phase | Intent | Receipt |
| --- | --- | --- |
| **0 — Foundation** | Measure before cutting | `REFACTOR_BASELINE.md`, `CLI_MODULE_MAP.md`, file-size advisory script |
| **1 — CLI/TUI splits** | Break rendering monoliths | `event_rendering/`, `tui/renderer/handlers/`, `tui/dialogs/`, `widgets/activity_card/`, `theme/` |
| **2 — Test mirror** | Tests follow modules | `backend/tests/unit/cli/tui/`, `frontend/`, orchestration service tests consolidated |
| **3 — Top-level CLI packages** | Stable import surfaces | `display/`, `session/`, `settings/`, `onboarding/` |

Phases 0–3 are complete. That is worth saying plainly because journey docs
age fast when the repo is actively moving.

What "complete" means in practice:

- The interactive renderer is a **package graph**, not a god file.
- Settings, sessions, and onboarding have **named homes** instead of leaking
  through `config_manager.py`.
- Contributors can grep `from backend.cli.settings import` and land in the right
  place on the first try.
- The largest remaining CLI files are **known exceptions** documented in
  `CLI_MODULE_MAP.md` (lifecycle, input, drain) — kept whole for semantic
  cohesion, not because I ran out of courage.

---

## The Backend Learned the Same Lesson

The CLI was not the only place monoliths hid. The backend decomposition wave
followed the same rule as the file-editing facade from
[Chapter 40](40-the-facade-pattern-and-the-smaller-file-api.md): **keep the
public import stable, move complexity behind it**.

Representative splits:

| Was | Now |
| --- | --- |
| `engine/tools/_file_edits.py` (~1,413 LOC) | Facade + `_file_edits_{symbols,handlers,multi,common}.py` |
| `inference/llm.py` | `inference/llm/` package (`core`, `config`, `stream`, …) |
| `inference/direct_clients_*_ops.py` | `inference/providers/` per vendor family |
| `context/context_pipeline.py` | `context/context_pipeline/` package |
| `context/canonical_state.py` | `context/canonical_state/` package |
| Context memory modules | `context/memory/` (`conversation_memory`, `session_memory`, …) |
| Compaction helpers | `context/compaction/` + `context/compactor/strategies/` |
| Ledger stream | `ledger/stream/` (`EventStream`, backpressure, coalescing, persistence) |
| Ledger infra | `ledger/infra/` (config, integrity, masking, tool metadata) |
| Execution runtime | `execution/runtime/`, `execution/aes/`, `execution/server/` |
| Orchestration stuck logic | `orchestration/stuck/` (`StuckDetector` + `patterns.py`) |
| Orchestration middleware | `orchestration/middleware/` (rollback, validators) |
| Utils cross-cuts | `utils/treesitter/`, `utils/async_helpers/`, `utils/lsp/`, `utils/http/`, `utils/terminal/` |

The pattern is consistent: a thin facade or package `__init__.py` preserves the
old import path; siblings hold the actual logic. Refactors become incremental
instead of cliff dives.

---

## Mechanical Discipline Beats Hero Refactors

Two tools made this wave different from earlier "I'll clean it up someday" passes.

### File-size advisory

`backend/scripts/verify/check_file_size.py` enforces a soft budget (500 LOC) and
hard budget (800 LOC) on new or changed CLI files. It does not pretend every
legacy file can be split overnight. It **stops the bleeding**.

### Import manifest

`docs/internals/import-manifest.json` records canonical import paths for
contributors and automation. When you are about to decompose a module, you check
who imports it first. Decomposition without an import map is archaeology with extra
steps.

### Reliability gate

`backend/scripts/verify/reliability_gate.py` bundles phase-appropriate pytest
suites for migration signoff — orchestrator units, step-guard coverage, knowledge
base tests, and optional integration/stress tiers. One command, cross-platform,
no provider lock-in.

This is the product decision underneath the tooling: **refactors are not done when
the file moves. They are done when the gate passes.**

---

## Vocabulary Before Another Rename Tsunami

While the splits were underway, I locked language in `docs/VOCABULARY.md` and
[ADR-016](../ADR.md#adr-016-grinta-vocabulary-contract).

The problem was subtle. Grinta had outgrown its inherited nouns. Docs said one
thing, packages said another, and every new contributor had to learn two
dictionaries.

The contract standardizes terms like **Session orchestrator**, **Compactor**,
**Outcome** (preferred over vague "result" language in ledger semantics), and
**Execution policy** as conceptual language for autonomy + security — while
admitting that code symbols may lag during transition.

This matters as a product decision because vocabulary is how you tell users what
you will not break. Lock the words before the next implementation sweep, or every
doc chapter becomes a time capsule that lies by accident.

---

## Prompt Cache Hygiene: MCP Moved Out of the Prefix

A quieter decision with real cost impact: MCP tool catalogs no longer bloat the
static system prompt.

`prompt_builder` and `conversation_memory` now render MCP as a **per-turn
user-role addendum** — wrapped in `<MCP_TOOLS>` — so the stable system prefix can
hit provider-side prompt caches. The system prompt intentionally omits MCP;
the addendum injects it without invalidating everything above it.

This connects directly to the open problem named in
[Chapter 07](07-the-road-ahead.md): compaction boundaries and cache-control
boundaries still need tighter coordination. But separating MCP from the prefix was
the prerequisite. You cannot align compaction with caching while MCP servers
change the system prompt every session.

See `docs/PERFORMANCE.md` for token-budget targets that assume this layout.

---

## Security Profiles Graduated: Standard, Hardened, Sandboxed

[Chapter 36](36-the-required-risk.md) made `security_risk` required and collapsed
autonomy to one honest knob. The execution profile story matured in parallel.

`settings.template.json` now exposes three tiers users should understand as
**different promises**, not marketing synonyms:

| Profile | What it does | What it does *not* do |
| --- | --- | --- |
| `standard` | Baseline local execution with analyzer + confirmation policy | Isolate the host |
| `hardened_local` | Stricter command policy: network installs, background processes, sensitive paths, workspace escape — blocked unless explicitly allowed | Sandbox or VM isolation |
| `sandboxed_local` | Reuses hardened command policy **plus** OS-native process isolation for **non-interactive** subprocess commands | Sandbox interactive PTY sessions; full PowerShell parity on Windows |

`sandboxed_local` is documented honestly in
[Chapter 33](33-the-small-async-wars.md): AppContainers on Windows, degraded
PowerShell behavior inside the sandbox, interactive terminals stay unsandboxed
because the threat model and latency cost differ.

The product decision: **do not sell one security slider when the runtime offers
three different postures.** Users choose how much policy and how much isolation
they want; docs must not collapse those into one reassuring word.

---

## Stuck Detection: Control vs Telemetry

Earlier journey chapters cited "10 heuristics" for stuck detection. That was true
of an earlier architecture where soft signals could trip the control path.

The current `StuckDetector.is_stuck()` is deliberately narrower. **Only hard
signals stop the agent:**

1. Exact action → observation repeats (or exact action → error repeats).
2. Monologue loops (same message text, no tool calls between).

Soft heuristics — semantic loops, A-B-A-B oscillation, token repetition, cost
acceleration, think-only loops, read-only inspection sweeps — remain available
for `compute_repetition_score` telemetry. They do **not** trip stuck recovery
anymore because they false-positive on legitimate iterative work (TDD, exploration,
refactoring passes).

This was a product decision, not a simplification for laziness: **the stuck counter
had become a progress tax.** An agent that is genuinely iterating should not
accumulate stuck warnings just because it is thorough.

Circuit breakers and iteration guards still exist as separate layers. Stuck
detection itself got honest about what it can prove.

---

## Provider Matrix: Data-Shaped Where Possible

Chapter 45 listed the catalog providers at the time of writing. The matrix kept
growing in the data-shaped direction the chapter described:

Anthropic, Cerebras, DeepInfra, DeepSeek, DigitalOcean, Fireworks, Google, Groq,
Lightning, **Moonshot**, Mistral, NVIDIA, OpenAI, OpenCode routes, OpenRouter,
Perplexity, Together, Vercel, xAI, and **Z.ai** — 22 catalog files under
`backend/inference/catalogs/`, with local discovery under
`backend.inference.discover_models`.

Adding a provider should still be "catalog + client ops when necessary," not a
fork in the agent loop. The decomposition wave made that truer: provider quirks
live in `inference/providers/` and capability modules, not scattered across the
orchestrator.

---

## What Is Still Large (On Purpose and Otherwise)

Honesty requires a "not yet" list. From `REFACTOR_BASELINE.md`:

**Still large, split candidates:**

- `backend/inference/direct_clients.py` (~1,180 LOC)
- `backend/context/conversation_memory.py` (~1,180 LOC)
- `backend/ledger/stream/__init__.py` (~1,160 LOC)
- `backend/context/prompt_window.py` (~1,130 LOC)

**CLI exceptions kept whole:**

- `tui/screen/lifecycle.py`, `tui/screen/input.py`, `tui/renderer/drain.py`,
  `tui/renderer/mixins/display.py`

The decomposition wave did not finish the repo. It **changed the default** from
"monolith until crisis" to "package early, facade imports, measure, gate."

---

## What Changed In Me

Chapter 45 said I wanted legibility over impressiveness. This phase taught me
what legibility costs in calendar time.

Splitting is not one heroic weekend. It is dozens of small moves: extract mixin,
mirror test, update import manifest, run reliability gate, fix the one caller that
imported the private symbol, document the exception, move on.

I also stopped treating narrative counts as architecture. "23 services" and
"9 compactors" are snapshots. The invariant is the **shape**: focused modules,
explicit pipelines, facades that do not lie, docs that point to current paths.

The product decision underneath all of it:

**Grinta is now maintained as a system strangers can enter.**

That is different from "Grinta works on my machine." It is the difference between
an engine and a project worth collaborating on.

---

← [The Product Surface Became Real](45-the-product-surface-became-real.md) | [The Book of Grinta](README.md) | [The Long Runs and Their Receipts](47-the-long-runs-and-their-receipts.md) →
