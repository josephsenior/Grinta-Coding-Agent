# 02. The Killed Darlings

Deleting something you are proud of takes a specific kind of engineering maturity.

Not because it was broken. Not because it was too hard to maintain. Not because you could not finish it.

Because it worked, was interesting, was technically impressive, and still had to die.

This chapter is about those features.

They were not mistakes in the naive sense. Most of them taught me important things. Some of them pushed me into research-level agentic design patterns. Some of them still live on in other forms. But eventually they all ran into the same question:

**Did they increase real task completion reliability enough to justify their cost?**

If the answer was no, they had to go.

That sounds clean when I write it down now. It did not feel clean while I was doing it. Deleting these systems often felt like cutting off proof that I had done hard work. That is why I am documenting them this carefully. I do not want the final repo shape to erase the cost of the decisions that made it possible.

---

## 1. The Multi-Agent Software Engineering Team

This was one of the most ambitious things I built.

Not a "planner plus executor" toy pattern. A full software engineering team of agents.

In the old codebase, this lived as the **MetaSOP** subsystem — over **20,000 lines of Python** across 51 source files. That is not a typo. Twenty thousand lines for a planning system that lived inside a coding agent.

It had everything a real software company's project management layer would want. Role profiles defined in YAML. Standard Operating Procedures with dependency graphs and conditional gating. Schema validation for every role's output so the system could detect when the Architect's response did not match the expected format and automatically re-prompt with a corrective hint. A provenance chain using SHA-256 hashes so you could trace any artifact back to the exact step and role that produced it.

It even had a failure taxonomy — ten categories of things that could go wrong, from `schema_validation` to `budget_exceeded` to `semantic_gap`, each mapped to a specific corrective strategy. If the QA step failed because a test assertion did not pass, the system knew to inject "Analyze failing assertion trace; propose minimal code diff to satisfy expected behavior" into the retry prompt. If the build broke, it knew to suggest dependency resolution. The system was trying to be smart about its own failures.

The earliest version went even deeper than that. I built an LLM-powered conflict predictor that would analyze upcoming steps and warn if two roles might clash over the same file or produce contradictory requirements. I built a predictive execution planner that estimated how long each step would take and optimized the execution order for parallelism. I built a patch scoring system that measured the quality of generated code changes across four dimensions — lint cleanliness, cyclomatic complexity, diff size, and content length — because I wanted the system to not just produce code but to judge whether the code it produced was any good.

There was even a document called `ARCHITECTURE_GAPS.md` that cataloged ten major categories of improvements the system still needed. It read like a roadmap for a product that was becoming its own company. That was the clearest sign I should have paid attention to earlier.

The idea was to model the entire software lifecycle as a coordinated multi-agent system. A single user request would be transformed into specialized work handled by roles such as:

- Product Manager
- Architect
- DevOps
- Security
- UI Designer
- Engineer
- QA / Verification

This was not random role-play. It came from a serious systems idea: large software work spans multiple artifacts and multiple concerns. Product requirements, architecture, infra, security, frontend, implementation, and validation are often different layers of the same task. So why force a single agent to reason about all of them in one pass if a specialized team can decompose the work more thoroughly?

On paper, it was beautiful.

The agent infrastructure supporting this was equally elaborate. The old codebase had five different agent types — over 9,000 lines of specialized agents, each with its own prompt templates, memory management, and execution strategy. There was a CodeAct agent that did the real work, a browsing agent that could navigate web pages, a read-only agent for code analysis, and more. The delegation system was a genuine parent-child architecture: a parent agent could spawn specialized child agents, each inheriting budgets and iteration limits, each running in its own state, each reporting back through a chain of command that looked like an org chart.

The controller behind all of this had 24 separate service files. Twenty-four. Each one handling a single narrow concern — action execution, budget guarding, circuit breaking, delegation, stuck detection, state transitions, and on and on. That level of decomposition was not lazy. It was the kind of over-engineering you do when you believe the complexity is justified because the system is going to keep growing.

And that was the trap. The system *was* going to keep growing. That was the problem, not the solution.

In practice, it was expensive.

And if I am being honest, it was flattering. There is a very specific ego hit you get from watching a system produce role-separated plans that look like a whole software company is thinking through your problem. It makes you feel like you built something profound. That feeling is dangerous when the execution economics are bad.

### Why The Team Model Was Attractive

The multi-agent system promised several things:

- more structured planning
- clearer artifact ownership
- deeper upfront analysis
- explicit treatment of enterprise concerns such as infra and security
- better decomposition of complex work

And it *did* produce more detailed plans.

That was the problem.

### Why The Team Model Died

The deeper the planning got, the more it started producing the kind of complete enterprise software plans that sound amazing in theory and become unimplementable in a real autonomous run.

The system would think in terms of:

- infrastructure metrics
- full lifecycle architecture
- detailed security controls
- deployment and operations requirements
- broad integration plans that sometimes assumed external services or environments that were not fully available inside the repo

That level of planning is impressive. It is also misaligned with the current state of AI execution.

A model can produce a detailed enterprise plan more easily than it can faithfully execute every detail of that plan over hours of autonomous work.

That mismatch matters.

A perfect plan is useless if the executor cannot carry it all the way through.

So the system created a strange failure mode:

- higher token cost
- slower execution
- more overhead
- more coordination complexity
- more surface area for drift
- lower ROI relative to a strong single agent that just does the work

For users with limited budgets, this was especially bad. The multi-agent team was burning money to produce planning depth that the implementation layer could not always cash out.

That is when I made the call: **kill it inside Grinta.**

### What Survived

I did not let that knowledge disappear.

The planning ideas and multi-artifact thinking were valuable enough that I spun them into a separate project: [Metasop](https://github.com/josephsenior/Metasop).

That matters because removal does not always mean regret. Sometimes it means rehoming a concept where it belongs. The MetaSOP code was serious enough — 20,458 lines of orchestration, schema validation, provenance, memory, and remediation — that it deserved to stand on its own rather than die inside a product that had moved past its need.

Inside Grinta, the conclusion was clear: a **single capable agent with disciplined planning and validation** was more cost-effective and more aligned with the actual goal of autonomous task completion.

What replaced the multi-agent team inside Grinta is more surgical: a task tracker tool that uses only update and view commands with canonical statuses persisted as a plain JSON list. The task validation service blocks the agent from declaring "done" when plan steps are still outstanding. The compactor reads the active plan file to anchor in-progress tasks as essential events that survive context compaction. The planning is simpler, the execution is cheaper, and the validation is harder to cheat.

The difference in philosophy is stark. The MetaSOP system assumed that better decomposition produces better outcomes. Grinta's current system assumes that better follow-through on simpler plans produces better outcomes. Those are fundamentally different bets about where quality comes from in autonomous work. I made the second bet because I watched the first bet fail — not because the decomposition was wrong, but because the execution layer could not sustain the fidelity the decomposition demanded.

---

## 2. The ACE Framework

ACE stood for **Agentic Context Engineering**.

This was one of the roughest removals because it touched a very seductive idea: an agent that improves itself over time by learning from its own execution history.

The framework revolved around the idea of a feedback cycle with components such as reflection and curation that would write learned knowledge into structured playbooks or context artifacts.

In the old codebase, ACE was a fully realized system — roughly 2,300 lines across 8 files, built around three agents that worked in a loop.

The first agent generated reasoning trajectories. It would look at a task, pull relevant strategies from a shared knowledge base called the Context Playbook, and produce a plan. The second agent reflected on what happened after execution — it analyzed outcomes, identified errors, and tagged each strategy as helpful, harmful, or neutral. The third agent curated: it took the reflector's insights and used them to update the Playbook itself, adding new knowledge and pruning entries that had been marked as harmful.

The Playbook was organized into eight sections: Strategies and Hard Rules, APIs to Use, Verification Checklists, Common Mistakes, Domain Insights, Tools and Utilities, Code Patterns, and Debugging Tips. Each entry could be individually scored by the reflection loop. The whole system supported what I called online adaptation — real-time learning during task execution — and tracked every run's results so the system could see its own improvement trajectory over time.

When I describe it now, I can still feel why it was so compelling. This was not a parlor trick. It was a genuine attempt to make context a living, evolving asset instead of a static blob of text that gets thrown away after every session.

The promise was obvious:

- the system gets better from experience
- useful patterns are extracted and reused
- context becomes a living asset, not just transient prompt text
- the agent evolves instead of repeating the same mistakes forever

This is the kind of idea that feels like the future.

### Why ACE Was Interesting

A coding agent that can only execute is one thing.
A coding agent that can *improve its own context model* is much more powerful.

ACE was trying to move Grinta from "task-solving machine" toward "self-improving knowledge system." That is a serious jump in ambition.

### Why ACE Died

Because the theory was cleaner than the reality.

The first problem was **token overhead**.

Self-improvement is not free. Reflection loops, curation logic, and rewriting shared playbooks all consume context and model calls. If the gain is small and the cost is persistent, the economics break quickly.

The second problem was **reliability**.

A self-improving system adds another layer of complexity to a product that already has enough ways to fail. Before a system is allowed to rewrite part of its own operating knowledge, you need very high confidence in its judgment. At Grinta's stage, that was not the best trade-off.

The third problem was the most important: **reliability over scope creep**.

Grinta's primary goal was not to become a research lab for self-modifying agent cognition. Its goal was to autonomously finish real engineering tasks with high reliability.

ACE was intellectually exciting. But in practice, it was burning meaningful overhead for a respectable yet not high-enough improvement.

That is not enough.

So I removed it.

For deeper details about the ACE implementation, the architectural experiments behind it, and what exactly each component was doing, the best route is to contact me directly. That part of the journey was real, serious, and extensive, but not all of it belongs in the live production architecture.

This one hurt in a quieter way than the multi-agent team. The team model felt expensive and noisy. ACE felt intelligent. Removing it felt like choosing discipline over a version of the future that I really wanted to be ready already.

---

## 3. Prompt Optimization

This one was fascinating.

I built a system where the model could auto-tune parts of its own prompt.

The implementation was substantial — over **10,000 lines** of prompt optimization infrastructure. The system tracked per-tool prompt variants for every tool the agent could use, measured which variants performed better, and swapped them in automatically. It was A/B testing for agent behavior, running continuously inside the agent loop.

The earliest version went further. I built a streaming optimization engine that processed real-time performance data as the agent ran — watching for performance anomalies, tracking context changes, and triggering prompt mutations on the fly. A separate prompt evolver would continuously create new variant candidates. The system was trying to become a live, self-tuning prompt laboratory.

I need to be honest about why I built this: it was partly engineering curiosity and partly a deep anxiety that I was not getting the prompts right manually. The idea that the system could figure out its own best instructions felt like the ultimate form of laziness masquerading as sophistication.

If you are building agents, that idea is almost irresistible. Prompting is one of the most critical factors in agent behavior. So the natural question becomes: why not let the system learn how to adjust the prompt based on task outcomes?

That was the experiment.

### Why Prompt Optimization Was Attractive

Prompt optimization promised:

- adaptive behavior improvement
- better alignment to recurring task patterns
- a way to encode learning without hardcoding every refinement manually

It is the sort of idea that makes an agent feel alive.

### Why Prompt Optimization Died

Because prompt growth is not free.

This is one of the most under-discussed realities in LLM systems: the more material you stuff into a system prompt, the more you are competing for the model's attention.

Large prompts do not just cost more. They create attention dilution.

Every extra section is another thing the model has to weigh. If the prompt keeps growing through auto-optimization, you do not get infinite wisdom. You often get:

- bloated instructions
- weaker salience of critical guidance
- higher chance of the model forgetting part of the prompt
- polluted context windows
- degraded behavior in exactly the situations where you hoped optimization would help

This was the breaking point.

A prompt optimizer that slowly makes the prompt less navigable is not optimization. It is slow sabotage.

So I killed it.

What replaced it is a more disciplined static prompt architecture. The system prompt is now assembled from a small number of structured partials — routing, autonomy, tools, critical instructions — and the prompt manager selects the right variant per model. The system prompt is structured, not grown. Context enrichment happens through events that inject workspace knowledge on demand, not by bloating the base prompt. And the agent checks in with itself periodically instead of continuously mutating its own instructions.

The prompt system in earlier versions was Jinja2-based, loading template files from per-agent directories and injecting runtime data, repository info, and conversation context through the template engine. That was flexible — too flexible. Combined with the prompt optimization layer, the prompt surface was essentially unbounded. Every template could grow independently, and the optimizer could push each one in a different direction.

Grinta's current prompt architecture works from static partials precisely because that era's lesson taught me that unconstrained prompt flexibility is a trap. You do not want a system that can say anything to the model. You want a system that says the right things and shuts up.

The lesson was important: **prompt quality is not just about more instructions. It is about keeping the important instructions cognitively visible to the model.**

---

## 4. Docker Runtime Execution for the Agent Itself

This is a subtle one, because Docker was not removed entirely.

There is a major difference between:

- using Docker to containerize the **target application** or surrounding infrastructure
- forcing the **agent runtime itself** to live inside a containerized execution model

The second version was far heavier.

### Why Docker Runtime Was Attractive

The old codebase had nearly **20,000 lines** of runtime infrastructure. To give you a sense of how seriously I took this: I built a warm pool system that kept pre-warmed Docker containers ready so the agent would not have to wait for cold starts. When a container sat idle too long, a watchdog reclaimed it. When a task needed full isolation, the system spun up a single-use container instead. There was GPU passthrough support, volume mounting, user ID isolation, and telemetry tracking the ratio of reused containers versus fresh ones.

Each agent type had its own container requirements. The browsing agent needed a container with a real browser and accessibility tree support. Every delegated sub-agent inherited or acquired its own runtime. I was building a container orchestration layer inside a coding agent.

That last sentence should have been the warning sign.

Containerized runtime execution opens real doors:

- isolation
- portability
- stronger boundaries
- a more Linux-like environment for Windows users
- the possibility of capabilities that are easier in Linux terminal ecosystems

This is also where terminal experience enters the story.

A lot of industry-grade coding agents lean on Linux-first terminal assumptions. PTY behavior, process control, and tools like tmux all fit more naturally into that world. Docker felt like a path to normalize some of that complexity.

### Why It Died as a Default

Because for a local-first CLI, it was too much overhead.

A containerized runtime for the agent adds:

- startup friction
- more operational complexity
- more places where local development can break
- a worse default experience for people who just want a powerful agent in their workspace

That did not mean terminal power stopped mattering.
It meant I had to find a better balance.

### What Replaced The Docker Runtime Default

Grinta's terminal manager is a first-class tool with three simple actions: open a session, send input, read output. Under the hood, each of these maps to typed ledger events that flow through the same event-sourced pipeline as everything else — meaning terminal sessions get the same persistence, replay, and recovery guarantees as file edits.

The runtime can still take advantage of tmux when it exists, but it does not require it. If tmux is not present, the system falls back to direct PTY management instead of refusing to start.

That distinction matters:

- **optional power** for users who want advanced terminal ecosystems
- **no mandatory infrastructure burden** for everyone else

This is a broader design principle in Grinta: advanced capabilities should be available, but they should not become a tax on every user.

---

## 5. Heavy Infra Dependencies: Redis and Async Database Thinking

Redis and async database infrastructure make sense in many serious distributed systems.

They also make perfect sense when you are still thinking like a hosted multi-user platform. The old server had Redis-backed rate limiting with per-endpoint quotas, Redis-backed cost tracking with tiered plans, a billing service wired to Stripe, an email notification service, and its own monitoring dashboard. That is a lot of SaaS infrastructure for a system that was about to become a local CLI tool.

But once Grinta became a local-first CLI, I had to ask a harder question:

**Are these dependencies still solving the user's real problem, or are they leftovers from the SaaS version of the architecture?**

The answer was clear enough that the dependency strategy changed.

Redis was removed from the core runtime path entirely. It stays only as an optional extra for users who want it in their own projects. The async database driver moved out of the required base and into an optional dependency group.

I removed Redis from the default path because a single-user local CLI does not need distributed coordination by default. Redis is excellent when you need shared caches, cross-process locks, and networked rate limiting across many workers. For Grinta's core use case, it mostly added operational tax: another service to bootstrap, another failure point, and another reason local startup could fail before the first task even runs.

PostgreSQL was a different decision. I did not kill it. I kept it optional.

That distinction matters. PostgreSQL is still the right tool for teams that want durable relational history, stronger transactional guarantees, or integrations that benefit from SQL-native querying. But forcing every local install to carry a database dependency would violate the local-first promise. Optional PostgreSQL gives power users a serious persistence path without making the default experience heavy.

I made the same trade-off in observability. Prometheus and Grafana are great tools. At scale, they are often the right answer. I removed them from the default architecture because Grinta is not shipping a mandatory distributed monitoring platform anymore.

Instead, I kept essential telemetry and observability only:

- structured logs for reproducible debugging
- event-level counters on critical paths
- latency and failure visibility around inference and tool execution
- explicit error traces tied to the event stream

That baseline is enough to diagnose real failures and improve the system without forcing every user to run a time-series database and dashboard stack.

The result: 43 required packages, zero distributed-systems infrastructure in the default install path.

That was not anti-infrastructure dogma. It was architecture matching the product shape.

A local-first agent should not drag a distributed-systems dependency burden by default unless it truly needs it.

This is one of the ways Grinta became more honest as a tool.

---

## 6. The Textual TUI

At one stage, Grinta had a Textual TUI story alongside the web-oriented experience.

Eventually, that did not survive as a core direction.

Why? Because maintaining multiple primary interaction models is expensive, especially in a project where the real engineering battle is already happening in orchestration, persistence, context handling, inference abstraction, safety, and runtime control.

The moment you keep too many front doors alive, the cost multiplies:

- more UI-specific bugs
- more surface area to keep consistent
- more product ambiguity
- more maintenance overhead for functionality that is not the core engine

So the non-essential pieces had to lose.

---

## 7. Cloud Runtime Providers

Grinta also moved away from cloud-runtime-style dependencies and integrations such as e2b, Modal, Daytona, and similar directions.

This removal matters because it reflects one of the deepest philosophical pivots in the project.

A hosted agent architecture tends to accumulate external execution providers because they solve real problems at scale.

But they also create:

- product coupling
- environmental assumptions
- deployment friction
- dependency sprawl
- a narrower path for users who simply want a local tool

Once Grinta committed to local-first as a principle, those providers no longer belonged in the core identity of the system.

---

## 8. The BrowsingAgent

The old codebase had a full browser-automation agent. I was proud enough of it to label it "Ultimate BrowsingAgent — From 6.5/10 → 9.5/10" in the source code, which tells you something about both my ambition and my ego at the time.

It could control a real browser, flatten the accessibility tree of a web page into text the model could reason about, track which pages it had visited and what actions it had taken, and parse the model's responses to extract the next browser action. It had its own prompt templates, its own response parser, and its own performance tracking.

It also required its own condenser — a separate context compaction strategy just for browser output, because screenshots and accessibility trees are extraordinarily token-expensive. Older browser observations had to be masked outside a recency window or the context would explode. When this condenser was alive, the total condenser count was twelve. When both the BrowsingAgent and its condenser died, the count dropped.

The BrowsingAgent died because Grinta committed to a local-first CLI identity. A browser-controlling agent needs a container runtime with a real browser, display forwarding or screenshot capture, and browsergym infrastructure. That is a heavy dependency chain for a tool whose users want to edit code in their terminal.

---

## 9. The Issue Resolver

The old codebase had an automated issue resolution system — over 6,000 lines of Python that could clone a repository, read a GitHub or GitLab issue, spawn an agent to generate a fix, and post a pull request. End to end. No human in the loop except for a simulated approval step.

I loved building this. The idea of pointing an agent at an issue tracker and watching pull requests appear is one of those visions that makes you feel like you are building the future of software development.

But it required the full Docker runtime, the container pool, and a working agent-in-a-sandbox loop. Once the Docker runtime died as the default, the Issue Resolver lost its foundation. It also tightly coupled the agent to specific platform APIs and authentication flows, which pushed against the local-first, model-agnostic direction.

Sometimes a feature dies not because it was wrong, but because the ground it stood on was removed for good reasons.

---

## 10. The Anti-Hallucination System

Inside the CodeActAgent, there was a dedicated hallucination prevention layer — a system I labeled "From 7.5/10 → 9.5/10" in the source code, which again tells you something about how I was keeping score with myself at the time.

The system tracked file operations across turns so it could tell the difference between a model that *said* it edited a file and a model that *actually* edited a file and then verified the edit. It would force the model to use tools instead of chatting when it should be working. It would automatically inject verification commands after file operations. It tracked how many hallucinations it had prevented, which is the kind of metric that makes you feel like a genius until you realize you are building an increasingly complex immune system for a disease that might be better treated at the source.

That is ultimately why it died. Grinta's safety architecture evolved in a different direction — instead of a dedicated anti-hallucination layer bolted onto one agent type, the safety concerns were distributed across the broader middleware pipeline and the event-sourced observation system. You do not need a hallucination detector when the event log shows you exactly what happened. Events do not lie. Models do.

---

## What These Removals Actually Prove

At a distance, someone might look at these deletions and think they represent wasted effort.

They do not.

They prove several things instead.

### 1. I was not building by hype

If a flashy system did not justify itself, I removed it.

### 2. I learned where current AI systems still break

Detailed planning is easier than reliable execution.
Self-improvement is easier to imagine than to operationalize.
Prompt expansion is easier than prompt discipline.
Containerized elegance is easier to admire than to make default-friendly.

### 3. I chose product truth over engineering ego

This is the important one.

It takes much less maturity to keep a feature because it is impressive than to delete it because it is not serving the real goal.

The current shape of Grinta is built on those deletions.

It is better because I let the wrong kinds of ambition die.

---

## The Real Lesson

A lot of agent projects try to look advanced.

I wanted Grinta to *be* advanced.

That means accepting that the measure of sophistication is not how many subsystems you can pile up. It is whether the final system is sharper, more reliable, more cost-aware, and more truthful because of the decisions you made.

The killed darlings were part of that sharpening process.

And some of the hardest architectural lessons in the entire project came from the features that no longer exist.

---

## What Comes Next

Removing features was not enough.

To make the surviving system strong, I had to rebuild its core architecture so that complexity could scale without turning the codebase into a monolith.

That is the next chapter.

---

← [The SaaS Fortress](01-the-saas-fortress.md) | [The Book of Grinta](BOOK_OF_GRINTA.md) | [The Architectural Gauntlet](03-the-architectural-gauntlet.md) →
