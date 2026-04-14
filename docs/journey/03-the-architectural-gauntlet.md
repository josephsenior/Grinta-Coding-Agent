# 03. The Architectural Gauntlet

If the previous chapters explain why Grinta changed direction, this one explains why it did not collapse under its own complexity.

Because building an agent is one problem.
Building an agent codebase that can survive months of growth without rotting is a different problem entirely.

This is where I became obsessed with architecture.

Not architecture as a buzzword.
Architecture as survival.

Grinta today is not a single giant loop with random helper files. It is a decomposed system with a serious orchestration layer, event-sourced state, recovery machinery, service boundaries, validation, and discipline around code quality. That shape did not appear automatically. It came from repeatedly feeling the pain of monoliths, debugging deadlocks, and deciding that if the project kept growing, the code had to remain understandable.

This chapter is probably the closest thing in this journey to a personality profile. I do not know how to watch a codebase rot without wanting to tear it open and redraw the boundaries. Some people tolerate architectural debt longer than I can. I feel it physically when I open a file and my brain resists reading something I wrote myself.

---

## The Monolith Broke First

A lot of solo projects start clean and become messy slowly.

That process is easy to underestimate because the project still works while the architecture is getting worse. You keep adding logic, the file gets longer, the conditionals get deeper, the responsibilities blur, and nothing fully explodes — until it does.

That happened here.

The orchestrator and other major components started out more centralized. As the agent gained:

- more tools
- more error cases
- more state transitions
- more safety checks
- more persistence requirements
- more retry logic
- more event-driven behavior
- more context management

it became obvious that a monolithic design would not scale.

This was not just about style. It was about maintainability, testability, and cognitive load.

If one file is trying to handle action generation, execution control, pending action tracking, observation processing, retries, stuck detection, safety gates, validation, and state transitions all at once, then every bug becomes harder to isolate and every feature becomes harder to add without fear.

So I decomposed it.

Not just the orchestrator. Everything.

I remember opening some of those swollen files and feeling dread before I had even started tracing the logic. That was the signal. If I did not want to read my own code, then the architecture was already charging interest.

That principle became a repo-wide priority.

---

## Clean Code Was Not Cosmetic

I care a lot about code quality, and I was stubborn about defending that standard even as the system grew.

Across the repo, I treated low cyclomatic and cognitive complexity as an operational requirement, not an aesthetic preference.

That outcome was not accidental. It came from deliberate decomposition, repeated refactors, and a refusal to let "it works" become the definition of acceptable code.

The codebase's low average complexity is not proof that the problem itself is simple. It is proof that I kept paying the refactor cost early instead of shoving it into the future.

That matters for two brutally practical reasons.

### 1. It protects the project from itself

Agent systems naturally accumulate complexity. They interact with models, files, processes, networks, state machines, retry logic, safety policies, and user-facing controls. Without aggressive simplification, the repo becomes unreadable very fast.

### 2. It makes reliability work possible

You cannot debug a stateful autonomous system effectively if every subsystem is tangled into every other subsystem.

Good architecture is not decoration. It is the precondition for diagnosable failure.

### The Art of Code Quality and Codebase Structure

Code quality is not a style preference. In an agent system, it is operational leverage.

When files are small enough to reason about, boundaries are explicit, and responsibilities are local, debugging stays linear. When modules become ambiguous and mixed, debugging becomes archaeological work. You are no longer solving the current bug. You are decoding accidental history.

That is why I treat codebase structure as part of reliability engineering. A clean structure reduces error blast radius, shortens incident resolution time, and makes both humans and agents less likely to introduce regressions while patching the system.

### Cyclomatic vs Cognitive Complexity

Cyclomatic complexity and cognitive complexity are related, but they measure different pain.

- Cyclomatic complexity measures branching surface area: how many execution paths a function can take.
- Cognitive complexity measures comprehension load: how hard the control flow is for a human to follow.

A function can have acceptable cyclomatic complexity and still be mentally hostile if it is deeply nested, context-switches across multiple concerns, or relies on subtle state transitions. That is why teams that only track cyclomatic complexity often miss the real maintenance risk.

Cognitive complexity is underestimated because it is less visible in dashboards and harder to compress into a single pass/fail gate. But in practice it is often the first thing that breaks velocity. It slows code review, increases misreads during incidents, and makes "small changes" far more dangerous than they look.

Keeping both low is not academic purity. It is how I keep Grinta modifiable under pressure.

---

## The 21-Service Orchestrator

One of the clearest examples of this philosophy is the orchestrator decomposition.

Earlier versions of the codebase already had the right instinct: the controller was decomposed into 24 separate service files — nearly 8,000 lines of controller code, each file handling one narrow concern. That was the instinct I inherited, but Grinta reshaped it.

Three services from that era died with the features they supported. The delegation service died when I killed the multi-agent team. The budget guard was simplified once Stripe-backed per-user billing went away. The telemetry service was folded into lighter-weight hooks. In their place, Grinta added services that matched its new identity — exception handling, step decision logic, and task validation — all born from pain points that only became visible after the agent became a single-process local CLI.

The orchestration layer was split into 21 focused services, each with a narrow job. Instead of one giant controller pretending to do everything, the system delegates responsibilities across services for action execution, state transitions, iteration control, lifecycle management, observation processing, pending action tracking, recovery, retries, safety, stuck detection, task validation, and more.

That list matters not because of the specific names, but because of what it reveals about how seriously the problem was decomposed.

Even that list hides the shape of the work. The top-level orchestrator is still over a thousand lines because coordination is genuinely hard. But the dangerous logic now lives where it can be named and tested. Event routing earned its own boundary because routing, delegation, and parallel worker orchestration were complex enough to drown the main loop. The pending action service exists because a single pending slot broke once overlapping async delivery became real — so now it tracks multiple outstanding actions. And there is a context facade whose sole purpose is to stop auxiliary services from reaching directly into the controller internals.

Each service exists because the agent loop is not a single thing. It is a bundle of concerns that need different rules, different tests, and different failure handling.

### What Each Service Actually Manages

The decomposition is not random. Each service maps to a specific failure mode I observed while building the system.

The **Step Decision Service** determines whether an incoming event should trigger an agent step at all. User messages always step. Agent messages step unless the system is waiting for user input. Condensation actions always step because the system needs to continue after memory compaction. But state-change observations, recall observations, and error observations never step — they are informational, not action-triggering. That decision tree was not obvious. I built it after watching the agent enter infinite loops where an observation would trigger a step, which would generate another observation, which would trigger another step. Separating "should I step?" from "how do I step?" killed that loop.

The **Step Guard Service** sits in front of every step and asks whether the agent is in a safe state to continue. It implements a warning-then-trip pattern: the first time a guard condition triggers (circuit breaker, stuck detection), it emits a warning with a planning directive that tells the model to change its strategy. If the same condition triggers again on the same action-reason pair, it trips harder. Only after a configurable number of warnings does the guard actually hard-stop the loop. This graduated response prevents a single transient error from killing an otherwise productive session.

The **Recovery Service** classifies exceptions into three buckets. Hard-stop exceptions — authentication failures, content policy violations, irrecoverable context window errors — transition the agent to `AWAITING_USER_INPUT` immediately because no amount of retrying will help. Rate-limit exceptions go to the retry queue with a doubled backoff multiplier. Everything else gets converted into an error observation that the agent can see and recover from, while the agent continues running. That classification was one of the most valuable pieces of work in the entire project, because the difference between "retry" and "die" determines whether the agent can survive real-world API instability.

The **Retry Service** owns the retry queue with exponential backoff bounded by a configurable maximum delay. It computes initial delay accounting for both rate-limit hints from the provider and consecutive error counts from the circuit breaker. This means the retry delay automatically increases when the system is under sustained pressure, not just when a single call fails.

The **Observation Service** matches incoming observations to the correct pending action by cause — preferring the stream ID linkage, falling back to the most recent pending action if the linkage is missing. It drops stale duplicate observations for background-only event types like recall, and it handles user confirmations and rejections as state transitions. That matching logic sounds trivial until you realize that async event delivery means observations can arrive out of order, and without correct matching, the agent processes observation B as the result of action A.

The **Safety Service** evaluates the security risk of every action before it executes. It delegates to the `SecurityAnalyzer` for rich pattern matching, falls back to `UNKNOWN` risk if the analyzer is unavailable, and then applies the autonomy controller's confirmation gates. In fully autonomous mode, the agent proceeds. In supervised mode, the agent pauses for user approval. The safety service does not decide whether an action is dangerous — the analyzer does that. The safety service decides what to *do about it*.

The **State Transition Service** enforces the state machine explicitly. It maintains a map of valid transitions — which states can follow which other states — and rejects invalid transitions with warnings. This sounds mechanical, but without it, the agent can end up in impossible states where it is simultaneously "running" and "finished" because two concurrent events both triggered state changes. The explicit state graph makes impossible states structurally impossible.

The **Task Validation Service** gets the final vote before a finish action can actually end the session. It walks the task tracker, recursively finds every step that is not marked as done, and if active steps remain, blocks the finish. This is the integrity constraint that prevents the most dangerous failure mode: an agent that confidently reports success while work is still incomplete.

### The Hot Path as a Sentence

Once those distinctions are explicit, the code gets sharper.

The hot path reads almost like a sentence: check prerequisites, check guards, get action, execute action, process observation, transition state, validate completion. Each clause has its own service, its own tests, its own failure mode.

And once the code gets sharper, the system becomes easier to trust.

---

## Why Event Sourcing Entered the Picture

This was one of the hardest architectural decisions in the whole project.

I moved Grinta to event-oriented persistence because snapshots alone could not answer the questions that matter during failure:

- what happened before the crash
- which action produced which observation
- whether replay can reproduce the same behavior
- whether state transitions are still trustworthy

That shift made the system more operationally serious. It also made the system more expensive to build. Ordering, recovery, and replay correctness all become first-class engineering problems the moment you commit to a durable ledger.

The detailed mechanics now live in [19-surviving-the-crash.md](19-surviving-the-crash.md). This chapter keeps the architectural point: decomposition gave those reliability concerns explicit homes instead of hiding them in one giant controller.

---

## Recovery and Guardrails Were the Same Problem

At first I treated "recovery" and "safety" as separate ideas.
In practice they were the same architectural concern: failure containment.

The system had to do all of this without collapsing into spaghetti:

- classify exceptions by recoverability
- retry only when retrying is rational
- block false finishes when plan state is incomplete
- detect loop behavior before it burns a session
- enforce policy before risky actions hit the environment

This is why the service decomposition mattered so much. Once those responsibilities moved into dedicated services, incidents became diagnosable and behavior became testable.

The deeper stuck and circuit-breaker story now lives in [20-circuit-breakers-and-hallucinations.md](20-circuit-breakers-and-hallucinations.md), because that subsystem eventually became large enough to deserve its own chapter.

---

## Architecture as Failure Containment

One of the strongest lessons of this project is that reliability is not mainly a prompting trick.

Reliability is architecture refusing to let a probabilistic model act without supervision from deterministic systems.

In Grinta, that shows up as explicit state transitions, pending action tracking, validation before finish, middleware gates around execution, and a persistence trail that can be audited after the fact. The goal is simple: make bad behavior visible early, reduce blast radius, and keep sessions recoverable.

That is what turned this from a clever prototype into a system I could trust under pressure.

---

## What I Learned from Decomposition

The deeper I went, the clearer one principle became:

**Big systems do not stay understandable by accident.**

If you want a project to grow while staying maintainable, you have to keep paying the simplification cost.

That means:

- breaking large files apart even when it is annoying
- naming boundaries clearly
- moving logic into focused services
- preserving testability as a first-class requirement
- refusing to accept complexity just because the domain is complex

This is one of the biggest differences between hacking something together and engineering something to last.

---

## Why This Chapter Matters

If someone looks at Grinta and assumes it is just a wrapper around an API plus a few tools, this is the chapter that should break that illusion.

The architectural gauntlet is where the project stopped being a clever experiment and became a serious system.

Not because it became larger.
Because it became more disciplined.

And that discipline is what made the later systems possible: context management, model-agnostic inference, security hardening, recovery, and the ability to keep evolving the repo without drowning in its own complexity.

---

## What Comes Next

Once the architecture could survive complexity, the next battle was keeping long-running sessions coherent.

That battle was not about persistence.
It was about memory.
It was about attention.
It was about the harsh reality that context windows are not just size limits — they are cognitive limits.

That is the next chapter.

---

← [The Killed Darlings](02-the-killed-darlings.md) | [The Book of Grinta](README.md) | [The Context War](04-the-context-war.md) →
