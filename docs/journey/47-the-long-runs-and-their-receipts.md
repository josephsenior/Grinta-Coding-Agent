# 47. The Long Runs and Their Receipts

> **Snapshot:** July 2026. This chapter distinguishes two separate Ouroboros
> runs and the evidence boundary around each one.

By July, I no longer needed another story about a ninety-second bug fix. I needed
to know what happened when Grinta stayed alive long enough for every weak seam to
become visible: provider failures, context pressure, malformed tool calls,
pending actions, process suspension, incomplete specifications, and the model's
ability to negotiate scope without quietly redefining success.

Two runs became part of that answer. They should not be merged into one result.

## Run A: The Public 106-Minute Trace

The first public artifact is under [`traces/ouroboros/`](../../traces/ouroboros/).
It records a 1 hour 46 minute session against an intentionally oversized task:

- a self-hosting functional compiler in Python
- Hindley–Milner inference, linear types, and effects
- a C11 runtime
- garbage collection and scheduling
- Raft and distributed-GC components
- a bootstrap equality requirement

The run used a MiMo v2.5 variant with a 200,000-token context limit. The public
folder contains a readable session, an audit summary, and a compressed raw log.
The files were added in commit `4ad1b0d62`.

What this run demonstrates is sustained execution and an inspectable sequence of
tool use, failures, fixes, and generated artifacts. It also demonstrates scope
negotiation: the generated project used simulated routing and other
simplifications to make progress inside the available execution window.

That is useful behavior. It is not the same thing as implementing every clause
of the original specification.

## Run B: The 273.5-Minute Sanitized Report

A second run on 9 July produced the report at
[`docs/evidence/2026-07-09-autonomous-run-report.md`](../evidence/2026-07-09-autonomous-run-report.md).
It is a different artifact, not a corrected duration for Run A.

The audit summary records:

| Metric | Recorded value |
| --- | ---: |
| Runtime state | `FINISHED` |
| Duration | 273.5 minutes |
| Events | 16,393 |
| Tool outcomes | 373 |
| Successful tool outcomes | 368 |
| Failed tool outcomes | 5 |
| File events | 123 |
| Recorded user turns after the initial turn | 0 |

The run encountered inference-provider connection failures, process suspension,
malformed model payloads, context pressure, and pending-action timeouts. The
important runtime signal is not that these failures disappeared. It is that they
were classified, surfaced, or recovered from without forcing the session into a
terminal error state.

## Three Different Meanings of “Success”

The run forced me to separate claims that I had previously allowed to blur:

1. **Runtime completion:** the orchestrator reached its `FINISHED` state.
2. **Repository validation:** the tests implemented in the generated repository
   passed.
3. **Specification conformance:** every requirement in the original task was
   implemented faithfully.

The evidence supports the first two for the reported run. It does not support
the third.

The generated project documented significant simplifications: simulated
bootstrap behavior, in-memory Raft state, incomplete runtime enforcement for
some type properties, and reduced distributed-GC behavior. A system can finish
cleanly and pass its own tests while still failing the stronger external
specification. Completion integrity therefore cannot end at “the agent ran the
tests it wrote.” The acceptance criteria must come from outside the generated
implementation and survive the whole session.

## What Changed Because of the Runs

These sessions made several later changes feel less optional:

- task requirements needed a durable home outside conversational summaries
- the generation budget had to be clamped against the real remaining context
- process suspension had to be distinguished from agent execution time
- pending actions had to be tracked and cleared individually
- provider capabilities, including prompt caching and context limits, had to be
  runtime facts rather than assumptions in a prompt
- evidence reports needed to state omissions and validation gaps explicitly

Those changes lead directly into the next chapter.

## The Evidence Boundary

Run A publishes a raw compressed trace. Run B publishes a sanitized report. The
second report omits raw prompts, absolute paths, full tracebacks, and the complete
event stream. That makes it useful evidence, but not a fully reproducible public
benchmark.

The correct claim is narrow: Grinta sustained two long autonomous executions,
generated large multi-file systems, encountered real runtime failures, and
reached completion states with passing generated tests. The artifacts also show
why none of that is enough, on its own, to claim full task compliance or broad
reliability across arbitrary repositories.

That narrower claim is stronger because another person can inspect where it
ends.

---

← [The Decomposition Wave](46-the-decomposition-wave.md) | [The Book of Grinta](README.md) | [The Continuity Contract](48-the-continuity-contract.md) →
