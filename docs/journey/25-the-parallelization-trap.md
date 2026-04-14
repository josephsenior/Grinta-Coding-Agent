# 23. The Parallelization Trap: When Speed Breaks the Agent

The premise sounds perfect: If an agent can read a file in one second, why not let it read ten files at once? Why not let it run a search, start a server, and edit a config all in the same batch?

It seems like an obvious upgrade. Humans multi-task when exploring codebases. CI pipelines run parallel jobs. If you want to make an agent faster and cheaper (by reducing sequence latency), just unlock parallel tool execution.

I fell for this premise. And it broke everything.

## The Illusion of Throughput

When I first considered parallelization for Grinta, I envisioned a massive throughput boost. The model could issue an array of parallel tool calls—`read_file`, `grep_search`, `cmd_run`—and process them all simultaneously.

But autonomous coding agents are not just glorified task runners. They are state machines that rely on an unbroken, deterministic chain of events.

When I tried aggressive parallelization, the architectural assumptions underlying the entire system began to fracture.

## Why Unchecked Parallelism Fails

### 1. The Event Sourcing Collapse

Grinta’s core relies heavily on an append-only event stream (`ledger/events`). Every action creates an observation, which creates the next action. If you run multiple mutating actions simultaneously (like writing to two files or running a modifying command), the strict ordering of the event stream is compromised.
When the agent needs to "undo" or self-correct, the rollback mechanism cannot guarantee what state it's returning to because the timeline is no longer linear.

### 2. The Middleware Pipeline Cannot Handle Superposition

As discussed in Chapter 22, the middleware contract depends on intercepting actions at `execute` and `observe`.
Imagine a `cmd_run` action that requires user confirmation. In a serial loop, execution pauses, the user confirms, and execution resumes.
In a parallel loop with mixed actions, the orchestrator triggers the `cmd_run`, pauses for confirmation, but *also* continues running a `file_edit` and a `search` in the background. The user hasn't approved the command yet, but the agent's context is already updating with the results of the other parallel actions. The causal feedback loop is destroyed.

### 3. Non-Determinism in the Context Window

An agent’s prompt context is fragile. If you execute five tools in parallel, in what order do their observations return to the prompt?
If one tool finishes early and another takes ten seconds, the agent's memory of events jumbles. Race conditions emerge not just in code, but in the model's physical "understanding" of what it just did.

## The Safe-Subset Solution

I realized that parallelization in agents is a throughput problem governed by strict safety bounds.

The solution was not to abandon parallelization, but to constrain it using a strict **Action Scheduler**.

Instead of blind concurrency, Grinta now evaluates batches of pending actions using a `ParallelBatchDecision`. The rule is simple: **Only read-only, non-mutating actions can run in parallel.**
The `ActionScheduler` whitelists specific prefixes:

- `read`
- `think`
- `search_code`
- `explore_tree`
- `get_entity`

If a batch contains *only* these actions, Grinta runs them concurrently, currently capped at 10 simultaneous threads to avoid overloading file descriptors and context limits.

If a batch contains even a single unsafe action (like `file_edit` or `cmd_run`), the scheduler immediately degrades to serial execution.

### Tool-Call Batching vs Action Scheduling

There is a second layer that often gets confused with scheduler parallelization: tool-call cardinality per assistant turn.

- In native tool-calling mode, the model may emit multiple independent tool calls in one turn.
- In string fallback mode (pseudo-XML parsing), the system intentionally accepts one function call per message for deterministic parsing.

Those are message-format constraints, not scheduler policy. The scheduler can still parallelize safe read-only actions after calls are parsed into actions.

## The Lesson

We often map human productivity metaphors ("do more things at once") onto AI agents. But agents lack human intuition for state reconciliation. When a human reads three files and edits a fourth, they implicitly understand the dependency graph of those actions. An agent relies entirely on the sequential integrity of its observation loop to build that graph.

By constraining parallelization to a "safe subset" of read operations, we preserve the deterministic feedback loop required for autonomous reasoning while still harvesting the latency benefits of parallel exploration.

Throughput should never cost you determinism. When it does, your agent isn't getting faster—it's just failing at a higher concurrency.

---

## What Comes Next

The next chapter returns to the epilogue perspective: what remains unfinished, where the architecture is still evolving, and what constraints still need better answers.

---

← [The Middleware Contract](23-the-middleware-contract.md) | [The Book of Grinta](README.md) | [The Identity and Execution Crisis](24-the-identity-and-execution-crisis.md) →
