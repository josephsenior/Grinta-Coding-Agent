# 48. The Continuity Contract

> **Snapshot:** 10–17 July 2026. This chapter records the continuity, memory,
> prompt-caching, shell-default, file-API, and CI work that landed after the
> decomposition wave.

The long runs exposed a mistake in how I talked about memory.

I had treated a good compaction summary as if it were durable task state. It is
not. A summary is written for the next model turn. Task state is written for the
system that must decide whether the work is finished.

When those two responsibilities share one document, the summary becomes
authoritative by accident. A model can omit an awkward acceptance criterion,
compress a blocked step into a vague sentence, or reinterpret the objective while
trying to make the conversation coherent. The next turn then inherits a cleaner
story and a less accurate contract.

## Durable Task State Left the Summary

The first task-state subsystem landed in commit `83a5ab697`. It introduced a
separate package under `backend/task_state/`, ledger actions and observations,
tool handling, storage, and TUI rendering.

The July 15 continuity work (`b26bbddfc` and `9155ea9b9`) made the boundary more
explicit:

- structured summaries preserve conversational continuity
- durable task state preserves objective, acceptance criteria, progress, and
  blockers
- compaction may reference task state, but it does not own it
- the prompt window renders the execution contract from structured state
- completion checks can consult something more stable than the model's latest
  prose summary

This is a small conceptual split with a large reliability effect. Memory answers
“what should the model remember?” Task state answers “what is the system still
obligated to finish?”

## Project Memory Became Orchestrator-Owned

On July 10, project memory moved into an orchestrator-owned architecture in
commit `e35189783`.

This was not a return to the self-improving prompt system described in the killed
darlings chapter. Project memory is explicit repository knowledge with controlled
read and update paths. It can preserve durable workspace facts and lessons, but
it does not silently mutate the core system prompt or claim to optimize itself.

The distinction matters. Memory can be useful without being sovereign.

## Prompt Caching Became a Capability

Earlier prompt-cache work focused on keeping a stable prefix and moving dynamic
MCP catalogs out of it. That was necessary but incomplete. A stable prefix does
not help if the selected provider or model does not support the caching mechanism
the runtime expects.

Commits `b8646a640` and `6229b5332` moved the decision toward capability-driven
behavior. The inference layer now asks what the active model supports before
applying caching behavior. The prompt should describe a capability only when the
runtime can actually use it.

This is the same principle as the self-knowing-agent chapter, applied later and
more concretely: runtime truth first, prompt claim second.

## The File API Lost One More Tool

Chapter 46 recorded a seven-tool API that included a dedicated `read_symbol`.
That was true during the cleanup wave and became outdated quickly.

On July 2, commit `1365596a3` removed the dedicated symbol-read tool while
composing the compaction layers. The current model-facing file API has six tools:

- `read_file`
- `find_symbols`
- `create_file`
- `replace_string`
- `multiedit`
- `undo_last_edit`

`edit_symbol` remains part of the journey because its removal taught an important
lesson: backend sophistication is not useful when the model cannot select the
schema reliably. `read_symbol` now adds a second version of the same lesson. A
tool can be coherent and still fail to justify its cognitive surface.

The current code in `backend/engine/tools/native_file_tools.py` is the receipt;
the earlier chapters remain snapshots.

## Native Windows Chose PowerShell by Default

The console-war chapters grew out of a Git-Bash-first period. On July 10, commit
`1af161bb6` changed onboarding and `settings.template.json` to prefer PowerShell
on native Windows.

This did not erase Git Bash, WSL, or the semantic shell abstraction. It changed
the default to match the environment most Windows users already have. The prompt
and executor still need to agree on shell identity, and cross-platform command
semantics are still a contract rather than a string substitution problem.

## Completion Became Immediate and Observable

Two July 14 changes (`ce94df862`, `78b63eab6`) tightened the path from completed
requirements to visible readiness. Settings and integration probes were made
more reliable, and completion-readiness state stopped lagging behind the event
that satisfied it.

This is UI correctness and control-plane correctness at the same time. If the
system is ready to finish but the interface shows stale state, the user loses
trust. If the interface says ready before the task contract agrees, the system
creates a false finish. Both surfaces must observe the same transition.

## CI Became Part of the Product Claim

The final July wave expanded unit, integration, end-to-end, and coverage work
across Linux and Windows. The important historical event is not a permanent
percentage—the threshold changed while shards and platform differences were
being corrected. The event is that cross-platform claims acquired cross-platform
gates, and coverage moved above the earlier baseline.

Commits `60ee4bb36`, `35bcfdee2`, `58837abe3`, and `785760631` are the relevant
receipts. Live CI status, not this chapter, is the authority on whether the gates
pass today.

## What Continuity Means Now

By the end of this phase, continuity was no longer one feature called “memory.”
It was a contract across several systems:

- the ledger preserves what happened
- summaries preserve enough conversational context to continue
- task state preserves what remains owed
- project memory preserves selected repository knowledge
- provider capabilities constrain caching and context behavior
- the UI reflects the current transition
- CI checks whether the cross-platform implementation still holds together

That is less magical than “the agent remembers everything.” It is also more
useful. Each kind of state has an owner, a purpose, and a failure boundary.

---

← [The Long Runs and Their Receipts](47-the-long-runs-and-their-receipts.md) | [The Book of Grinta](README.md) | [The Road Ahead](07-the-road-ahead.md) →
