# 22. The Middleware Contract: Order Is Architecture

Middleware is often dismissed as plumbing; in agent systems, middleware order is policy.

If you run the wrong check at the wrong stage, you do not get a small bug. You get the wrong action touching the machine, the wrong cost being charged, or the wrong signal being logged too late to matter.

That is why this chapter matters.

## The Pipeline Is a Governance Layer

Grinta's tool pipeline wraps every invocation in a shared `ToolInvocationContext` and runs middleware in two explicit stages:

1. `execute` (before dispatch)
2. `observe` (after result)

That sounds simple until you realize what this enables:

- pre-execution policy gates
- post-execution integrity updates
- shared metadata across layers
- deterministic blocking when safety checks fail

The context can be blocked with a reason at any stage, which means middleware is not just a logger. It can be a hard decision point.

## Why Order Changes Outcomes

Imagine these checks out of order:

- telemetry before validation
- cost tracking after execution
- rollback snapshot after a risky write

All three are "implemented," yet all three are operationally wrong.

Good middleware architecture is not "did we add the feature?" It is "did we place the feature at the right point in the execution lifecycle?"

That distinction decides reliability.

## The Rollback Story Was a Real Lesson

One of the most practical examples in Grinta is rollback integration.

There was already rollback machinery in the codebase, but it was effectively orphaned from the invocation path. The fix was not to invent a new subsystem. The fix was to integrate checkpointing as middleware so risky actions automatically get a pre-execution snapshot.

The rollback middleware now creates checkpoints before action types like:

- `FileEditAction`
- `FileWriteAction`
- `CmdRunAction`

And it stores checkpoint IDs in invocation metadata for downstream consumers.

That means rollback stopped being an optional manual idea and became a default behavior in the execution path.

## Execute vs Observe Was Not Cosmetic

A lot of teams blur pre and post hooks. That is expensive in agent systems.

In Grinta, the split is explicit for a reason:

- `execute` is where you prevent harm.
- `observe` is where you reconcile reality.

For rollback, that means:

- create snapshot before risky execution
- update audit context afterward when observation and audit identifiers are available

Without this separation, you either snapshot too late or log incomplete evidence.

## Defensive Failure Behavior

The pipeline is deliberately defensive.

If a middleware throws unexpectedly, the invocation can be blocked with a middleware-stage reason instead of letting silent partial behavior continue.

That is not paranoia. It is containment.

A middleware failure inside a coding agent is not "internal only." It can directly impact filesystem or command execution outcomes.

## The Middleware Set Reflects Product Values

Look at what is in the middleware stack and you can read the product's values:

- safety validation
- circuit breaking
- context window control
- cost quotas
- telemetry
- blackboard coordination
- auto-check hooks
- logging

Those are not independent features glued together. They are an execution constitution.

Each layer answers one question:

- Is this safe?
- Is this affordable?
- Is this coherent with current context constraints?
- Is this observable and auditable?
- Can we recover if it goes wrong?

When those questions are answered in the same pipeline, behavior becomes predictable.

## Why This Matters More Than Prompt Tweaks

Prompt quality can improve action selection.

Middleware quality determines blast radius when selection is wrong.

That is why I treat pipeline design as architecture, not implementation detail.

If the model is probabilistic, the execution boundary must be deterministic. The middleware contract is where that boundary lives.

## The Rule I Keep Now

When adding any new execution feature, I ask one question first:

Where in the pipeline contract does this belong?

If I cannot answer that clearly, the feature is not ready.

Because in autonomous systems, correctness is not only what you do. It is when you do it.

---

## What Comes Next

The next chapter tackles one of the most tempting mistakes in autonomous agent design: assuming that more speed and parallelization automatically leads to better outcomes, and how I fell into the parallelization trap.

---

← [Who Grades the Agent](21-who-grades-the-agent.md) | [The Book of Grinta](README.md) | [The Parallelization Trap](23-the-parallelization-trap.md) →
