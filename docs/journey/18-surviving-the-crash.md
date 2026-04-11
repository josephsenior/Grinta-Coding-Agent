# 18. Surviving the Crash: Ledger, WAL, and Replay Reality

There is a special kind of pain in autonomous coding systems.

You watch the agent do everything right for 35 steps. It scopes the problem, edits the correct files, runs the right tests, and is one step away from a clean finish. Then the network blips. Or your laptop sleeps. Or the process gets killed during a write.

In normal software, you retry the request.
In agent software, a crash can erase recent memory, planned intent, and execution context.

That gap taught me a hard truth very early: a coding agent is not a request handler. It is a long-running state machine, and state machines either survive failure or lie about correctness.

## The Night This Became Non-Negotiable

The architectural decision in this chapter was not made in a clean design session.

It was made after a brutal run where the agent had already done meaningful work, then died in a bad window between execution and persistence. On restart, the story looked coherent, but the trace was incomplete. I could not prove what had actually happened.

That is the worst state for an autonomous system: confident outputs with uncertain lineage.

From that point on, durability was no longer a performance detail. It was an integrity requirement.

## Snapshots Were Not Enough

My first instinct was classic snapshot state: keep the current status in storage and update it every step.

It looked fine until the first serious failure scenarios:

1. Crash between action execution and state write.
2. Crash during state write itself.
3. Resume on a partially updated state where the model had no auditable trail.

A snapshot tells you where the agent ended up. It does not tell you how it got there. For autonomous systems, that "how" is everything.

## Why the Ledger Became the Spine

Grinta moved to append-only event history as the source of truth.

The core stream object is intentionally compositional:

- `EventStream` handles pub/sub and delivery.
- `BackpressureManager` owns queue pressure policy.
- `EventPersistence` owns durable writes, WAL recovery, and optional SQLite acceleration.

This separation matters. If stream delivery, queue policy, and persistence live in one giant class, every reliability bug becomes impossible to localize under pressure.

## Backpressure Is a Product Decision

Most teams talk about backpressure as a low-level detail. In agents, it is a product behavior.

When the event queue fills, what should happen?

- Drop oldest events?
- Drop newest events?
- Block and wait?

Grinta supports all three. It also tracks operational counters like high-watermark hits and drop rates, because silent pressure is how corrupted sessions are born.

Critical events get special handling. They are not treated like ordinary telemetry.

## Durability Without Freezing the Loop

Persistence has two conflicting goals:

1. Do not lose events.
2. Do not block the agent loop on every write.

That is why the durability layer uses an asynchronous writer with explicit queueing and retry behavior:

- Dedicated writer thread.
- Bounded queue (default size 4096).
- Micro-batching (up to 16 events per flush cycle).
- Short batch drain window (20ms) to improve throughput.
- Exponential retry on transient flush failures (up to 3 attempts, starting at 100ms).

This is the kind of boring engineering people skip in conference demos. It is also exactly what prevents an overloaded run from collapsing when persistence gets slow.

## The WAL Contract

The Write-Ahead Log design in Grinta is intentionally simple and brutal:

1. Write event JSON to `*.pending` marker.
2. Write canonical event file.
3. Remove `*.pending` marker.

On restart, recovery scans for leftover `*.pending` markers:

- If canonical file exists, marker is stale and cleaned.
- If canonical file is missing, pending payload is recovered into canonical event.

That one contract turns "random crash timing" from data loss roulette into deterministic recovery logic.

## Not All Events Are Equal

Some events are too important to risk in async buffers.

In Grinta, critical control and error events are forced through synchronous persistence paths. This includes control actions like `finish`, `reject`, `change_agent_state`, and high-signal observations like `error` and `agent_state_changed`.

That decision is expensive in the micro sense and invaluable in the macro sense. If the process dies, those events are already on disk.

## Replay Is Not "Load Last State"

A serious replay system does more than restore history.

The replay layer in Grinta strips irrelevant events (for example environment noise), replays deterministic actions, and can verify divergence by hashing expected and actual observation content after each replayed step.

That means replay is not only recovery. It is also a correctness probe.

If replay diverges, you know exactly where the system behavior stopped being deterministic.

That capability changed debugging psychology.

Before replay discipline, postmortems were guesswork wrapped in intuition. After replay discipline, failures became inspectable artifacts. That does not make incidents pleasant, but it makes them diagnosable.

## The Unsexy Safeguards

Two details look minor but save real sessions:

- Payload size caps with truncation for pathological oversized events.
- Optional local SQLite acceleration for faster durable reads and writes on disk-backed stores.

Neither one is glamorous. Both reduce outage surface area when sessions get long and noisy.

## What This Chapter Cost Me

I used to think reliability was about writing fewer bugs.

Building this taught me reliability is mostly about write ordering, queue pressure policy, and recovery semantics you can explain at 3 AM when production is on fire.

It also taught me that trust in agent systems is cumulative.

Users do not trust an agent because one run looked impressive. They trust it because, after crashes and retries and messy real sessions, the system still tells the truth about what happened.

Crash survival is not a feature on top of the agent. It is the floor under everything else.

---

← [The Mind of the Agent](17-the-mind-of-the-agent.md) | [The Book of Grinta](README.md) | [Circuit Breakers and Hallucinations](19-circuit-breakers-and-hallucinations.md) →
