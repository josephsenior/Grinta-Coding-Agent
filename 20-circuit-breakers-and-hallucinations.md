# 19. Circuit Breakers and Hallucinations: Paying the Infinite Loop Tax Once

One of the most expensive lessons in autonomous coding is this:

LLMs are not fragile; they are stubborn.

When they pick a bad strategy, they can pursue it with terrifying consistency.

I have watched an agent spend dozens of steps trying to fix a bug it created itself five minutes earlier. Not because it lacked capability, but because it lacked a strong enough signal that its current path was dead.

That is what I call the Infinite Loop Tax. You either pay it in architecture or pay it in runaway token burn, broken files, and false confidence.

## Why This Problem Looks Smaller in Demos

Short demos hide loop pathology.

In a 3-minute showcase, even weak loop controls can look fine because the system has not had enough time to drift. In real tasks, with real repositories and long execution chains, drift compounds. Minor misread signals become repeated no-progress behavior. Repeated no-progress behavior becomes cost burn and confidence theater.

That is why this chapter is long on mechanics.
Loop control is not an optional guardrail for edge cases. It is central infrastructure for autonomy.

## The Wrong Mental Model

I used to treat "stuck" as one pattern: repeated command, repeated error.

Reality was uglier. Agents get stuck in many ways:

- Different commands with the same no-progress outcome.
- Endless thinking with no real action.
- Read-only inspection loops that never transition into edits.
- Context growth spirals where each step gets more expensive and less useful.

A single stuck check was never going to hold.

## Stuck Detection Became a Multi-Heuristic System

Grinta's `StuckDetector` evolved into layered heuristics, each targeting a different failure mode.

### 1. Pattern repetition in action-observation cycles

The detector checks repeating action and observation sequences, including pairwise repetition patterns over recent windows. This catches classic loops where the model keeps issuing structurally similar calls and receiving structurally similar failures.

### 2. Semantic loop detection

This one matters more than literal matching.

The detector extracts intent categories from actions and outcome categories from observations, then computes:

- intent diversity
- failure rate

If diversity drops below 0.3 while failure rate exceeds 0.75 in the recent window, the agent is considered semantically stuck even if exact commands differ.

### 3. Token-level repetition

If the last three agent messages are identical and non-trivial (longer than 50 characters), that is treated as a hard repetition signal.

This catches the model mode where it starts "speaking in circles".

### 4. Cost acceleration checks

The detector inspects prompt-token growth over recent steps.

If prompt context grows by more than 50,000 tokens in five steps, or remains above 100,000 while still climbing rapidly, it is flagged as runaway behavior.

This protects reliability and cost.

### 5. Think-only loops

If the last 10 actions are all `AgentThinkAction` with no real tool execution, it is considered stuck.

This is important for models that over-plan and under-act.

### 6. Degenerate read-only loops

Read-only exploration is often legitimate, so this check is conservative by design.

It only triggers in extreme cases: 20+ read-only actions, zero writes, and less than 10 percent command diversity.

That catches true polling loops without punishing healthy codebase reconnaissance.

## Repetition Score Before Full Stop

Binary stuck/not-stuck decisions are late signals. By the time they fire, you already burned budget.

So Grinta also computes a repetition score (0.0 to 1.0) from multiple indicators:

- action repetition
- observation error density
- intent diversity collapse

That gives the system a chance to self-correct before a hard stop.

## Circuit Breaker: The Final Authority

The stuck detector diagnoses. The circuit breaker decides.

The breaker tracks four independent failure channels:

1. Consecutive errors.
2. High-risk action attempts.
3. Repeated stuck detections.
4. Error-rate spikes over a moving window.

Once thresholds are exceeded, it can pause or stop execution.

That authority boundary matters.

If the same component both proposes action and decides whether it is still healthy to continue, failure containment collapses into self-justification. The breaker exists to keep that separation explicit.

## Adaptive Thresholds Saved Legitimate Complex Tasks

A static breaker was too blunt. Hard limits that protect simple tasks can prematurely kill complex refactors.

So thresholds scale adaptively by:

- task complexity bands (1-3, 4-6, 7-10)
- iteration runway (with additional headroom for larger budgets)

This avoids punishing hard tasks while still preventing degenerate loops.

## One Subtle Fix That Reduced False Trips

I added per-tool consecutive error tracking.

Without it, unrelated failures from different tools stack into one global counter and trip the breaker too early. With per-tool tracking, the system can distinguish "one tool failing repeatedly" from "normal multi-tool exploration under uncertainty".

That was a small code change with outsized operational impact.

## Safety Layer Integration

Loop control alone is not enough. A looping agent can drift into risky commands.

Grinta's command safety layer classifies operations into risk tiers and can block critical patterns before execution. This includes destructive and exfiltration-prone command families.

The practical effect is simple:

- stuck logic protects reliability and cost
- safety logic protects system integrity

You need both.

## The Real Philosophy Shift

I stopped trying to "prompt the model into perfection."

Now the architecture assumes imperfection:

- the model will hallucinate sometimes
- it will overcommit to bad strategies sometimes
- it will need hard constraints sometimes

A mature agent system is not one that never fails; it is one that notices failure fast, limits blast radius, and recovers with dignity.

The practical translation for readers is simple:

- good prompts reduce avoidable errors
- good loop controls contain inevitable errors

You need both. But only one of them can guarantee your token budget does not disappear into a persuasive spiral.

---

## What Comes Next

Loop containment solves one kind of damage. The next chapter addresses another: risky actions on the host itself.

If this chapter is about stopping unproductive loops, the next one is about preventing high-consequence mistakes even when the loop is progressing.

That is where command-risk analysis, policy gates, and honest safety boundaries become non-negotiable.

---

← [Surviving the Crash](19-surviving-the-crash.md) | [The Book of Grinta](BOOK_OF_GRINTA.md) | [The Safety Sandbox Is Not Optional](21-the-safety-sandbox-is-not-optional.md) →
