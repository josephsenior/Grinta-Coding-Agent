# 44. The Empty Folder Trials

This chapter is not marketing. It is a lab note.

There is a class of agent capability that cannot be measured by benchmarks or demonstrated by cherry-picked examples. It is the ability to start from nothing — an empty directory, a natural-language task description — and produce a working system.

In late March 2026, I ran Grinta against the Raft/RFT advanced consensus task twice. Both times, it succeeded. This chapter is about what that proves and what it does not prove.

---

## The Task

The task description, roughly:

> Build a local distributed key-value store using Raft-style consensus. Pure Python, asyncio, no external Raft libraries. It should support a cluster of nodes, leader election, log replication, and fault tolerance.

Starting state: an empty directory. No scaffold, no tests, no architecture document. Just the prompt.

---

## What Grinta Completed

Over both runs, Grinta produced a working implementation that included:

- **Cluster management** — node discovery, cluster membership, heartbeat protocol.
- **Leader election** — randomized timeout-based election with term tracking and vote requests.
- **Log replication** — append-only log with commit indexing, follower consistency checks.
- **State machine application** — committed log entries applied to the key-value store.
- **Client interface** — a simple API for `get`, `set`, and `delete` operations routed through the leader.
- **Fault tolerance** — node failure detection, leader re-election, log consistency recovery.
- **Tests** — unit tests for election, replication, and failure scenarios.
- **README** — usage instructions and architecture overview.

The code compiled, the tests passed, and the cluster maintained consistency under simulated node failures.

---

## What It Struggled With

The runs were not perfect. The same weaknesses appeared in both:

- **Consistency edge cases** — the initial implementation handled simple partition scenarios but showed gaps in log matching under certain concurrent failure patterns. The fix required explicit prompt guidance.
- **Split-brain avoidance** — the first pass did not handle the case where a partitioned node rejoins with stale state. The agent needed a second pass to add proper safety checks.
- **Test coverage depth** — the tests covered happy-path and basic failure scenarios but did not stress-test network partitions or byzantine edge cases.
- **Configuration ergonomics** — the cluster configuration was hardcoded rather than file-based. A human would have abstracted it earlier.

These are real limitations. They are also the kind of limitations that separate a demo from a production system. The agent can build a working prototype. It cannot yet build a battle-tested distributed system.

---

## What the Run Proved

1. **Grinta can build nontrivial distributed systems from scratch.** A Raft implementation is not a toy. It requires understanding a complex protocol, translating it into correct async Python, and handling failure modes that are not in the training data. The agent did all of that.

2. **The architecture supports multi-hour autonomous sessions.** The Raft task took sustained execution across dozens of tool calls, file edits, test runs, and fix iterations. The event stream, checkpoint, and replay mechanisms kept the session coherent across the full duration.

3. **The agent can recover from its own mistakes.** When tests failed, it read the output, diagnosed the issue, and fixed the code. It did not loop on the same broken approach. It adapted.

4. **The quality gate caught incomplete work.** In both runs, the agent attempted to finish before handling edge cases. The finish gate blocked it, surfaced the gaps, and the agent addressed them before declaring completion.

---

## What It Did Not Prove

1. **Production readiness.** A working prototype is not a production system. The Raft implementation was correct for the scenarios tested but was not hardened for adversarial conditions, large cluster sizes, or real network partitions.

2. **Consistency across arbitrary tasks.** Two runs on one task do not generalize. The agent needs to demonstrate this capability across a wider range of complex, open-ended problems.

3. **Human-level judgment.** The agent did not make architectural trade-offs with the awareness of a senior engineer. It made reasonable choices, but it did not document why it chose one approach over another, and it did not anticipate failure modes that were not explicitly described in the task.

4. **Reliability under hostile conditions.** The task was well-specified. Real engineering often is not. The agent's performance on ambiguous, contradictory, or adversarial task descriptions is a separate question.

---

## The Honest Receipt

Grinta succeeded on the Raft/RFT consensus task twice. That is a real capability signal. It means the agent can hold a complex system model in context, produce coherent code across multiple files, test and fix its own output, and recover from failures without human intervention.

But the gap between "succeeded twice on a well-specified task" and "reliable autonomous engineering" is still large. The first proves something about the architecture. The second would prove something about the field.

I am publishing this lab note because evidence matters more than claims. The receipts are in the code. The limitations are in this chapter.

If you want to try the same task: start with an empty directory, give the prompt, and see what happens. Then compare receipts honestly.

---

← [The Plugin Boundary](43-the-plugin-boundary.md) | [The Book of Grinta](README.md) | [The Road Ahead](07-the-road-ahead.md) →
