# 37. The Vendor-Neutral Bench

I have a complicated relationship with benchmarks.

Most of the public ones — SWE-bench, HumanEval, the various agent leaderboards — answer the question *“which model resolves more issues from this canned set?”* That is a useful question if you are a model vendor. It is the wrong question if you are building an agent, because by the time the benchmark runs the agent and the model are intertwined: the harness shapes the prompts, the harness controls the tool surface, the harness retries on failure, the harness decides when “done” means done. You are scoring the harness as much as the model, and the score does not transfer to your own harness.

The honest question I wanted to be able to answer was different:

> *Given the same task, what does Grinta do — and how does that compare to what Aider, Claude Code, OpenHands, and a Copilot-style loop do — judged on dimensions I actually care about: did it finish, did it follow instructions, did it use tools sanely, did the code hold up, did it recover from failure?*

That question does not have a public benchmark behind it. So I built the smallest possible internal one, and called it the agent eval pack.

This chapter is about what the eval pack is, what it deliberately is not, and the principles that fell out of trying to score systems that were never designed to be compared.

---

## What the Pack Is

An eval pack is a JSON document with five required keys: `pack_id`, `version`, `agents`, `metric_weights`, and `tasks`. A results document, separately, is one agent’s recorded outcomes against the pack. Both are validated by `backend.evaluation.agent_eval_pack`, and the scorer produces a per-task and per-category summary.

Each task entry describes a discrete piece of work — a bug fix, a refactor, a multi-file feature, a recovery scenario — and optionally carries a `budgets` block (turns, latency seconds, cost in USD) and a `recovery_required` flag. The category is free-form so a pack can group tasks by theme (`refactor`, `debug`, `cross-file`, `regression`, `cold-start`, etc.) and the score breaks down by category in the final summary.

Each result entry records, per task: a binary `success`, five 0–5 scores (`verification`, `instruction_adherence`, `tool_discipline`, `code_quality`, `recovery`), and the three measured budgets. The scoring logic combines them into a per-task final score and an overall agent score.

The whole thing fits in a single Python file. It deliberately does not attempt to *run* anyone else’s agent. The pack is the rubric and the scorer; the runs are produced out-of-band, by a human operator (or a separate harness) executing each task with each agent and recording the results. That separation is the whole point of the design.

---

## Why the Scorer Refuses to Drive the Agents

I went back and forth on this for a week. The seductive version of the eval pack would be a runner that takes a list of `(agent, task)` pairs and executes each one, automated, comparable, hands-off.

I did not build that, deliberately. Three reasons.

**First, the agents do not have compatible control planes.** Aider is a CLI you pipe a prompt into. Claude Code has its own session model. OpenHands runs as a server and you talk to it over HTTP. A Copilot-style IDE loop is *fundamentally* interactive. Anything that pretends to drive all four uniformly will quietly favor whichever one its abstraction was designed around — most likely the one the author uses every day. The pack would become a Grinta-shaped scorer wearing a vendor-neutral hat.

**Second, the runs need a human in the loop to be honest.** Two of the five 0–5 metrics — instruction adherence and code quality — are not mechanically observable. A test pass tells you `success`. It does not tell you whether the agent ignored the “don’t touch the test file” constraint, or whether the working code is also maintainable code. Pretending those metrics are automated is how benchmarks become Goodhart traps.

**Third, the runs need to be reproducible *outside* this repository.** A pack should be runnable by someone who has never installed Grinta. If the scorer hard-coded calls into our own runtime, the score would only mean something inside our walls. By keeping the pack a JSON contract with a small validator, anyone can run any agent however they want, record the results in the standard format, and feed them into the scorer.

The scorer is intentionally the *small* piece. The expensive piece — actually running the agents — is the operator’s problem, and the operator is the only honest authority for the qualitative scores anyway.

---

## Score Composition: What the Numbers Mean

The composition is opinionated and I want to lay out *why*, because every choice here is a judgment.

**The five 0–5 metrics are normalized to 0–1 and weighted.** The weights live in the pack itself, not in the scorer, so different packs can emphasize different concerns. A “debugging” pack might weight `recovery` heavily; a “refactor” pack might weight `code_quality` heavily; a “quick edit” pack might collapse most of the weight onto `success` and `instruction_adherence`.

**`success` is binary and weighted alongside the qualitative scores.** Not multiplied through. A task that the agent resolved correctly but with bad tool discipline still loses points. A task that the agent failed but did so with clean retries and graceful recovery still earns *some* points. This is a deliberate refusal of the “success times quality” framing that most benchmarks use, because that framing makes failed tasks indistinguishable from each other regardless of *how* they failed.

**Failure caps the score at 49.** I argued with myself about this number for a while. The intent: a failed task should never outrank a successful one, even one with mediocre quality scores. Capping at 49 ensures that any successful task scoring 50+ beats any failed task. The cap is loud and crude on purpose; subtle weighting would have introduced the same Goodhart risk I was trying to avoid.

**`recovery_score` only counts when the task’s `recovery_required` flag is set.** Asking an agent to recover from a failure that did not occur is meaningless; scoring an agent on it would penalize agents that simply got things right the first time. The pack itself has to declare which tasks are recovery tasks. The scorer respects that declaration silently.

**Budget penalties are applied multiplicatively, capped at 25%.** If an agent overruns the turn / latency / cost budgets, each overrun deducts a fraction of the final score proportional to the overrun ratio, with a hard ceiling. The cap matters: an agent that burned 10x the cost budget but produced a perfect result should not score zero. It should score lower than an agent that produced the same result on budget. Budget is a *signal*, not an *override*.

---

## Why Vendor-Neutral Is Hard

Calling the pack “vendor-neutral” is a claim, not a property. The pack format does not enforce neutrality; the operator has to.

Three traps I tried to design around:

1. **Tasks worded in tool-specific language.** A task description that says *“use the `apply_patch` tool to fix this bug”* favors agents whose tool surface includes `apply_patch`. The pack’s task descriptions should describe *outcomes*, never *means*. The scorer cannot enforce this, but a reviewer can.

2. **Categories that map cleanly onto one agent’s features.** If half the pack is “MCP server integration” tasks, the agents without MCP support look bad on a dimension that does not represent general competence. Categories should be capability-shaped (`refactor`, `debug`, `recover`), not feature-shaped.

3. **Metrics that hide harness work.** Tool-discipline, in particular, depends on what tools the harness exposes. An agent with a richer tool surface has more opportunities to mis-discipline. The pack documents this explicitly: `tool_discipline_score` reflects *the agent’s use of the tools available to it in its native harness*, not a normalized comparison across agents.

The honest version of vendor-neutrality is *“the scoring math does not assume any agent’s architecture.”* It is not *“the resulting scores are directly comparable as model quality.”* I would rather state that limit out loud than build a leaderboard that papers over it.

---

## What I Use This For

Two purposes, both internal.

**Regression detection inside Grinta.** When I change the prompt, the toolset, or a piece of middleware, I want to know whether average task quality moved. Running the same pack against the new build and comparing aggregate scores is a faster, cheaper signal than waiting for a real user report. The category breakdown tells me *where* it moved, which usually points at exactly which subsystem the change broke.

**Sanity-checking the “Grinta vs ___” framing in the README.** The competitor comparison table in the README makes claims that are easy to read as marketing. Running a small eval pack against Grinta and at least one of the competitors, with the same operator scoring both, is the only thing I trust to back those claims. The pack itself is not a marketing artifact — the runs are not published — but the discipline of being able to run it changes how I write the comparison rows.

The pack is small. The point of it is small. I am suspicious of any agent benchmark that grows into a kingdom of its own; the moment a benchmark becomes the goal, it stops measuring what made it useful.

---

## What I Am Not Claiming

I want to close this chapter the way I started it: with what the eval pack is *not*.

- It is **not** a leaderboard. There is no scoreboard, no public ranking, no continuous integration pipeline that runs it on every release.
- It is **not** a substitute for SWE-bench-style public benchmarks. Those answer a different question and they answer it for an audience that needs cross-model comparison at scale. This pack answers an internal question for an audience of one.
- It is **not** an automated runner. The runs are produced by a human operator following a defined task description and recording the outcomes. Automation would be cheaper; honesty is more important.
- It is **not** a finished product. The five 0–5 metrics are a starting set, not the only possible set. A future revision will probably add a `safety_score` for how the agent handled HIGH-risk operations, and possibly a `dependency_hygiene_score` for refactors that touched package manifests.

What it *is*, today: the smallest scorer I could write that lets me ask a serious question across multiple agents, get a number back, and trust that the number reflects the question I asked rather than the harness I happened to ship. That is enough for now.

---

← [The Verbose Status](37-the-verbose-status.md) | [The Book of Grinta](BOOK_OF_GRINTA.md) | [The Road Ahead](07-the-road-ahead.md) →
