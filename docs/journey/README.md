# The Book of Grinta

**A development memoir about building, deleting, and rebuilding a local-first coding agent.**

By Youssef Mejdi, AI Engineering Student, 4th Year

> **Reading contract — history, not configuration.** These chapters preserve what
> I believed, built, measured, removed, and later corrected. An older chapter can
> be historically accurate and technically outdated at the same time. I keep the
> old event and add a dated correction instead of rewriting the past. For current
> installation, settings, architecture, and security behavior, use
> [USER_GUIDE.md](../USER_GUIDE.md), [SETTINGS.md](../SETTINGS.md),
> [ARCHITECTURE.md](../ARCHITECTURE.md), and
> [SECURITY_CHECKLIST.md](../SECURITY_CHECKLIST.md).

> **Evidence contract.** Exact counts are snapshots, not permanent product
> properties. Claims with durable repository evidence are indexed in
> [EVIDENCE.md](EVIDENCE.md). Memoir-only claims are identified as such rather
> than being presented as reproducible benchmarks.

## Start Here

Grinta began in September 2025 as an attempt to build far more than a coding
agent: a multi-tenant SaaS platform with a web interface, container orchestration,
specialized agents, self-improving prompts, and several layers of cloud
infrastructure. Much of that code worked. Much of it also made the product more
expensive, harder to reason about, or less useful to the person sitting in front
of a repository.

The project changed direction. The cloud platform was removed from the core. The
multi-agent committee was removed. Prompt optimization, heavy container pools,
and several retrieval experiments were removed or rehomed. What remained was a
local execution loop surrounded by deterministic systems for tool use, recovery,
context pressure, task validation, and observable failure.

The most useful parts of this story are not the feature counts. They are the
decisions:

1. **Subtraction can be architecture.** A working subsystem can still be the
   wrong subsystem for the product.
2. **Agent reliability is largely runtime engineering.** Streaming mergers,
   state transitions, pending actions, file grounding, and completion gates can
   make a model look better or worse without changing the model.
3. **A local-first product has a different threat model.** Policy gates and
   optional process isolation reduce risk, but they do not turn the host into a
   disposable VM.
4. **Long context is not durable task state.** Summaries help a model continue a
   conversation; they should not be the authoritative record of acceptance
   criteria and unfinished work.
5. **Evidence must travel with the claim.** A finished runtime state, a passing
   generated test suite, and full compliance with an original specification are
   three different claims.

This is also a personal record. I built parts of Grinta while studying, made bad
decisions while exhausted, and sometimes treated persistence as a substitute for
scope control. The lesson is not that 3 AM work is admirable. It is that fatigue
damages judgment, and that shipping, asking for review, and making the system
legible to other people are engineering decisions too.

## The Short Version

If you have less than an hour, read these chapters:

1. [The SaaS Fortress](01-the-saas-fortress.md) — the original product and the
   pivot away from it.
2. [The Killed Darlings](02-the-killed-darlings.md) — what was removed and why.
3. [The Context War](04-the-context-war.md) — why long sessions became a systems
   problem.
4. [The Verification Tax](14-the-verification-tax.md) — why “done” needs
   independent signals.
5. [The Small Async Wars](33-the-small-async-wars.md) — five concrete runtime
   failures that looked like model failures.
6. [The Decomposition Wave](46-the-decomposition-wave.md) — making the product
   maintainable after it became usable.
7. [The Long Runs and Their Receipts](47-the-long-runs-and-their-receipts.md) —
   what two public July runs prove and do not prove.
8. [The Continuity Contract](48-the-continuity-contract.md) — the later split
   between conversational memory and durable task state.
9. [The Road Ahead](07-the-road-ahead.md) — the unfinished parts.

## Timeline

The filenames preserve repository history, so their numbers are not a clean book
sequence. The order below is the intended reading order.

### Identity, ambition, and subtraction

- [Preface — Why This Story Matters](preface-why-this-story-matters.md)
- [00 — The Meaning of Grinta](00-the-meaning-of-grinta.md)
- [01 — The SaaS Fortress](01-the-saas-fortress.md)
- [02 — The Killed Darlings](02-the-killed-darlings.md)

### Architecture under pressure

- [03 — The Architectural Gauntlet](03-the-architectural-gauntlet.md)
- [04 — The Context War](04-the-context-war.md)
- [05 — The Giants' Playbook](05-the-giants-playbook.md)
- [06 — The System Design Playbook](06-the-system-design-playbook.md)
- [08 — The First Fixed Issue](08-the-first-fixed-issue.md)
- [09 — The 3 AM Decisions](09-the-3am-decisions.md)
- [10 — The Model-Agnostic Reckoning](10-model-agnostic-reckoning.md)
- [11 — The Console Wars](11-the-console-wars.md)
- [12 — Open Source Was the Better Product Strategy](12-open-source-was-the-better-business.md)

### Hidden systems and reliability

- [13 — The Hidden Playbooks](13-the-hidden-playbooks.md)
- [14 — The Verification Tax](14-the-verification-tax.md)
- [15 — Prompts Are Programs](15-prompts-are-programs.md)
- [16 — The Pragmatic Stack](17-the-pragmatic-stack.md)
- [17 — The Mind of the Agent](18-the-mind-of-the-agent.md)
- [18 — Surviving the Crash](19-surviving-the-crash.md)
- [19 — Circuit Breakers and Hallucinations](20-circuit-breakers-and-hallucinations.md)
- [20 — The Safety Sandbox Is Not Optional](21-the-safety-sandbox-is-not-optional.md)
- [21 — Who Grades the Agent](22-who-grades-the-agent.md)
- [22 — The Middleware Contract](23-the-middleware-contract.md)
- [23A — The Identity and Execution Crisis](24-the-identity-and-execution-crisis.md)
- [24 — The Parallelization Trap](25-the-parallelization-trap.md)
- [25 — The Observability, Cost, and Latency Triad](27-the-observability-black-hole.md)
- [26 — The Weight Divide](30-the-weight-divide-local-vs-hosted.md)

The former “Myth of the Committee” chapter was merged into
[The Killed Darlings](02-the-killed-darlings.md). There is intentionally no
link to the removed file.

### Productization and later corrections

- [28 — The Two Lives of the Terminal](32-the-two-lives-of-the-terminal.md)
- [29 — The Small Async Wars](33-the-small-async-wars.md)
- [30 — The Fuzzy Match Heresy](34-the-fuzzy-match-heresy.md)
- [31 — The Self-Knowing Agent](35-the-self-knowing-agent.md)
- [32 — The Required Risk](36-the-required-risk.md)
- [33 — The Verbose Status](37-the-verbose-status.md)
- [34 — The Vendor-Neutral Bench](38-the-vendor-neutral-bench.md)
- [39 — The Semantic Memory That Survived](39-the-semantic-memory-that-survived.md)
- [40 — The Facade Pattern and the Smaller File API](40-the-facade-pattern-and-the-smaller-file-api.md)
- [41 — The Mode Split](41-the-mode-split.md)
- [42 — The Interface Returned](42-the-interface-returned.md)
- [43 — The Plugin Boundary](43-the-plugin-boundary.md)
- [44 — The Empty Folder Trials](44-the-empty-folder-trials.md)
- [45 — The Product Surface Became Real](45-the-product-surface-became-real.md)
- [46 — The Decomposition Wave](46-the-decomposition-wave.md)
- [47 — The Long Runs and Their Receipts](47-the-long-runs-and-their-receipts.md)
- [48 — The Continuity Contract](48-the-continuity-contract.md)
- [Epilogue — The Road Ahead](07-the-road-ahead.md)

## Historical Changes That Commonly Confuse Readers

### File tools

Several chapters accurately describe an earlier six-tool API built around
`read`, `create`, and `edit_symbol`. A later cleanup renamed tools, removed
`edit_symbol`, briefly introduced `read_symbol`, and then removed that dedicated
read tool as the compaction and file-reading surfaces converged.

As of **17 July 2026**, the model-facing file API in
`backend/engine/tools/native_file_tools.py` contains six tools:

- `read_file`
- `find_symbols`
- `create_file`
- `replace_string`
- `multiedit`
- `undo_last_edit`

Older names remain in their original chapters because those chapters explain the
decision at that time. Dated notes point forward to this final shape.

### Interface

The original Textual interface was removed during the local-first pivot. A later,
operational Textual TUI returned as the primary interactive surface. Piped input
uses a separate non-interactive path. Both events are true.

### Server transport

FastAPI and Socket.IO belonged to the hosted/server phase and survived for part
of the transition. They are not part of the current core architecture. The
current product routes TTY input to the Textual app and piped input to the
non-interactive runner.

### Security profiles

`standard`, `hardened_local`, and `sandboxed_local` describe different promises.
The sandboxed profile adds OS-native, process-scoped isolation for supported
non-interactive commands; interactive terminal sessions remain outside that
boundary. None of the profiles should be described as a VM or complete host
isolation.

### Windows shell

Earlier chapters describe Git Bash as the practical Windows default. On
**10 July 2026**, onboarding and the template changed to prefer PowerShell on
native Windows. The semantic shell contract and Git Bash support remain.

## Evidence and Current References

- [Journey evidence index](EVIDENCE.md)
- [Current architecture](../ARCHITECTURE.md)
- [Current settings](../SETTINGS.md)
- [Reliability and trust model](../RELIABILITY.md)
- [Security checklist](../SECURITY_CHECKLIST.md)
- [Support matrix](../SUPPORT_MATRIX.md)
- [Vocabulary](../VOCABULARY.md)
- [Refactor baseline](../REFACTOR_BASELINE.md)
- [Changelog](../../CHANGELOG.md)

The project is not finished. The point of this book is not to make it look
finished. It is to preserve the sequence of decisions clearly enough that the
next person can distinguish an old truth, a current truth, and an unverified
claim.

