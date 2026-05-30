# 08. The First Fixed Issue

There is a specific kind of silence when something you built actually works.

Not "runs without crashing" works. Not "the tests pass" works. The kind of works where you type a natural language instruction into a terminal, walk away, come back, and the problem is solved. The code is changed. The tests pass. The diff is clean. The agent wrote a message explaining what it did and why.

That silence is not pride. It is disbelief.

You spend months building event streams, state machines, orchestration layers, compaction strategies, stuck detectors, tool pipelines, prompt architectures. You spend weeks on filesystem safety, terminal abstractions, cross-platform workarounds. You argue with yourself about whether the circuit breaker threshold should be four or six. You delete entire subsystems because they made the agent slower instead of smarter.

And then one afternoon the agent fixes a real bug in real code, and for about thirty seconds, you do not know what to feel.

---

## What "Working" Actually Means

I need to be precise about this, because the bar for "working" in autonomous code agents is deceptively easy to fake.

A demo that edits a file and prints "done" is not working. A system that generates plausible-looking code but doesn't verify it is not working. A chatbot that suggests changes and asks you to apply them manually is definitely not working.

Working means the agent:

1. Understood the task from a natural language description.
2. Read the relevant files on its own.
3. Identified the root cause on its own.
4. Made the correct changes.
5. Ran the tests to verify.
6. Updated its own plan to reflect what was done.
7. Finished cleanly — not because it ran out of tokens or hit a timeout, but because it decided the work was complete.

That seventh step is harder than it sounds. The agent is not allowed to declare "done" unless its plan is terminal. Every step in the task tracker must be marked as completed or explicitly marked as blocked with a reason. If the agent tries to finish while work is still outstanding, the system blocks it and tells it to go back and either finish the remaining steps or update the plan honestly.

That constraint was not there from the beginning. I added it because early versions of the agent had a nasty habit of declaring victory prematurely — finishing with a confident summary while quietly leaving behind half-broken code. The validation service exists because I learned that an agent's self-assessment cannot be trusted without structural enforcement.

---

## The Bug That Made It Real

I wish I could tell you the first bug the agent fixed was something dramatic. A security vulnerability. A race condition. Something that would make a good story at a conference.

It was an off-by-one error.

A loop that should have included the upper bound was excluding it. The kind of bug that every programmer has written and every programmer has spent too long staring at before seeing it. The agent read the file, found the loop, recognized that the range was one short, changed `range(1, n)` to `range(1, n + 1)`, ran the tests, watched them pass, updated its plan, and finished.

The whole thing took maybe ninety seconds.

I had spent months building infrastructure so that an AI model could do in ninety seconds what a human developer would have done in five minutes. That math does not sound impressive until you realize the human developer also spent fifteen minutes finding the file, ten minutes re-reading the context, five minutes second-guessing themselves, and another ten minutes making sure they did not break anything else. The agent's ninety seconds included all of that.

But the real significance was not the speed. It was the shape of the behavior.

The agent did not just produce the right output. It followed the right process. It planned before acting. It validated after changing. It updated its own tracking. It finished deliberately. That process — plan, act, verify, close — was the entire architectural thesis of the project, and watching it execute end-to-end was the first moment when the months of infrastructure stopped feeling like overhead and started feeling like investment.

---

## What I Watched For

After the first successful task, I did not celebrate. I watched.

I watched for the failure modes I had already cataloged. Does the agent get stuck in loops? Does it repeat the same failed action? Does it spiral into increasingly desperate attempts when it hits an obstacle? Does it lose track of what it was doing after context compaction? Does it confuse its own observations with the user's instructions?

The stuck detector was built for exactly this kind of paranoia. It computes a 0.0 to 1.0 repetition score for proactive self-correction, and it watches for six independent failure patterns, each born from a specific real failure I observed.

The first pattern is **repeated action-observation cycles** — the agent doing the same thing and getting the same result over and over. The second is **identical error messages** — the same error appearing multiple times without the agent changing its approach. The third is **monologue loops** — the agent using the `think` tool repeatedly without ever taking a concrete action, spiraling into deeper analysis without executing anything. The fourth is **oscillating patterns** — the agent alternating between two failing strategies, switching from A to B and back to A repeatedly. The fifth is **semantic loops** — a more insidious pattern where the actions look different textually but produce identical outcomes, requiring deeper comparison than string matching. The sixth is **context window pressure** — the system keeps compacting and the agent keeps losing the context it needs, producing a cycle of forgetting and rediscovering.

That last pattern is exactly where this chapter touches [04. The Context War](04-the-context-war.md). In a live run, context failure appears as a loop, a stall, or a confused retry. Underneath that visible symptom is the quieter systems problem of memory discipline.

Each one of those heuristics came from watching a real failure. Not a theoretical failure mode I anticipated during design. A real failure I watched happen during testing and then reverse-engineered into a detector. That is the difference between defensive engineering and paranoid engineering. Defensive engineering anticipates categories. Paranoid engineering has specific memories.

The stuck detection integrates with the circuit breaker through the step guard service. When the stuck detector fires, it does not immediately kill the session. Instead, it records the detection and emits a warning with a planning directive — a message injected into the agent's observation stream that essentially says "you appear to be stuck in pattern X, change your strategy." The step guard tracks how many times this warning has fired for the same action-reason combination. Only after hitting a configurable threshold does it escalate to a hard stop.

This graduated response was essential. Early versions of the stuck detector were too aggressive — a threshold of three consecutive errors would trip the circuit breaker during what was actually a normal multi-step debugging process. The current threshold of six provides enough runway for genuine retries while catching real loops. The circuit breaker also adapts its thresholds based on task complexity and iteration budget, so a long complex task gets more runway than a simple one.

---

## The Finish Protocol

The finishing flow deserves its own explanation because it reveals something about how I think about trust.

When the agent calls the finish tool, it must provide a summary message, a completion status, any blockers that prevented full completion, suggested next steps, and optionally lessons learned — observations about the task that might be useful for future runs. The lessons learned field is not cosmetic. If the agent discovers something genuinely useful during a task — a quirk of the codebase, a pattern that worked, a dependency that behaved unexpectedly — that information gets stored and can be injected into the debug prompt tier for future sessions.

That is where this chapter starts leaning on two later ones. [13. The Hidden Playbooks](13-the-hidden-playbooks.md) is about where reusable scar tissue and repository knowledge should live once the task is over. [15. Prompts Are Programs](15-prompts-are-programs.md) is about how those lessons can be surfaced without turning the base prompt into a landfill.

But providing that information is not enough. The task validation service independently checks the plan state. It walks the task tracker, recursively finds every step that is not marked as done, and if any remain active, it blocks the finish with a specific error. The agent then has to go back, actually complete the work, update the tracker, and try again.

The task tracker itself is more than a checklist. It is a persistent JSON file (`active_plan.json`) that the agent maintains throughout the session with `update` and `view` operations. Each step has three states — `todo`, `doing`, and `done` — and the tracker enforces ordering. The validation service reads this file and performs recursive descent through nested steps, because a parent step with three child steps is only "done" when all three children are done. That recursive check matters because the agent sometimes marks a high-level step as complete while leaving sub-steps unfinished.

This is not a quality-of-life feature. It is an integrity constraint.

I built it because I realized that the most dangerous failure mode of an autonomous agent is not crashing. It is confidently reporting success while the work is incomplete. A crash is visible. A false completion is invisible until someone discovers the broken code hours or days later.

The validation service supports different validator types. A `TestPassingValidator` can require that test suites pass before the session ends. A `DiffValidator` can require that actual file changes match expected patterns. A `CompositeValidator` chains multiple validators with configurable thresholds — you can require all validators to pass, or a majority, or at least one. That flexibility exists because different tasks have different completion criteria: some tasks are done when the code compiles, some when the tests pass, some when a specific diff pattern appears in the changed files.

The full philosophical argument behind that stack lives in [14. The Verification Tax](14-the-verification-tax.md). This chapter is the first time the loop worked in practice. That chapter is why I no longer think the model should be allowed to grade its own homework.

The validation service makes false completion structurally difficult. Not impossible — the agent could theoretically mark all steps as done without actually doing them — but difficult enough that the failure mode shifts from "silent incompletion" to "deliberate dishonesty," which is a much harder failure for a well-prompted model to produce.

That distinction — between making failure visible versus making failure impossible — runs through a lot of Grinta's design. I do not trust the model to be perfect. I trust the system to make imperfection obvious.

---

## The Moment After

The first fixed issue was not the moment I knew Grinta would succeed. I am still not sure it will succeed.

It was the moment I knew the architecture was not delusional. Months of infrastructure — the event sourcing, the state machine, the orchestration decomposition, the compaction subsystem, the stuck detection, the tool pipeline, the validation service — had finally produced something that could do the thing it was designed to do.

That sounds like a low bar. It is not.

Most complex systems never reach the point where all their pieces work together to produce the intended behavior. They work in isolation. They pass unit tests. They look right on architecture diagrams.

But the integrated behavior — the end-to-end flow where every layer has to trust every other layer — is where the hidden gaps show up.

The first fixed issue was the first end-to-end proof that those gaps were small enough to bridge.

It did not mean the system was reliable. It was not. Early runs had maybe a 40% success rate on non-trivial tasks. The agent would get stuck, or lose context, or misunderstand the scope, or try to fix things that were not broken. Each failure became a specific detector, a specific prompt adjustment, a specific architectural constraint.

But it worked once. And working once — genuinely, not in a demo, not with a cherry-picked example, not with a human secretly guiding it — is the difference between a research project and an engineering project.

Research asks: "Is this possible?"
Engineering asks: "Is this reliable?"

The first fixed issue answered the first question. Everything since then has been the second.

---

## Why This Matters If You Are Not an Engineer

If you are reading this and you do not write code for a living, here is why this chapter matters:

Building an autonomous coding agent is not primarily an AI problem. It is an infrastructure problem. The AI model — the LLM — is the easy part. You call an API, you get text back. That has been possible since GPT-3.

The hard part is everything around the model. How do you give it the right information without overwhelming it? How do you let it execute code safely? How do you know when it is stuck? How do you prevent it from lying about its own progress? How do you recover when it crashes in the middle of a task? How do you make all of that work across different operating systems, different models, different programming languages?

The first fixed issue was the proof that all of those "how do you" questions had working answers. Not perfect answers. Working answers.

And in engineering, working answers you can iterate on are worth more than perfect designs that never ship.

---

← [The System Design Playbook](06-the-system-design-playbook.md) | [The Book of Grinta](README.md) | [The 3 AM Decisions](09-the-3am-decisions.md) →
