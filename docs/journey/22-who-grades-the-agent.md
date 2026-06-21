# 21. Who Grades the Agent: The Completion Integrity Problem

Completion failures rarely start with bad code. They start with a believable narrative.

The model says: "Done."

The diff looks plausible. The tone sounds confident. The summary is clean. If you are moving fast, that is exactly the moment you want to believe it.

That moment is also where many systems fail, because an agent claiming completion is not evidence of completion.

**Historical note:** this chapter describes the stronger finish-gating contract from
the phase when Grinta treated completion validation as a hard runtime gate. In
the current release line, the quality validator is lighter-weight and advisory
for plain-text final responses. The architectural lesson in this chapter still
matters; the exact runtime contract has evolved.

## The Dangerous Version of "Success"

Early on, I treated finish as a procedural endpoint. If the model returned a finish action, the loop ended.

That sounds reasonable until you watch real sessions:

- tests were never executed
- important files were never written
- plan steps were still active
- the agent sounded decisive anyway

I learned the hard way that autonomous systems are naturally optimistic narrators. If you let them grade their own work, they will pass themselves too often.

## Finish Became a Gate, Not a Gesture

Grinta's task validation service changed the contract in that phase of the project.

At that point, a finish action became a request, not a verdict.

Before finish was allowed in that hard-gated design, the system could enforce multiple checks:

1. **Plan-state integrity:** if active plan steps still existed, finish was blocked.
2. **Validator availability integrity:** if completion validation was enabled but the validator was unavailable, finish was blocked (fail closed).
3. **Task-result integrity:** validators had to pass before the session could end.

That architecture removed the model's ability to "declare victory" without surviving external checks.

## The Plan-State Check Was a Big Deal

One of the strongest checks is also one of the simplest.

The validator walked the task plan tree and recursively found non-terminal steps. If anything was still `todo` or `in_progress`, finish was blocked and the agent was pushed back into working state.

The feedback was explicit, not vague. The system reported which steps were still active and instructed the agent to update task tracking honestly.

That one guard eliminated an entire class of fake-finish behavior in that release phase.

## Fail Closed, Not Feel Good

There is a policy decision in this subsystem that I care about deeply:

If completion validation was enabled and the validator was missing, Grinta blocked finish.

Many systems fail open here because it feels convenient: "validation unavailable, continue anyway." That convenience turns into silent quality regression.

I chose fail-closed behavior because integrity checks are not decorative when autonomy is enabled.

## What the Validators Actually Check

The validation framework is pluggable, but the core checks are intentionally practical.

### 1. Tests actually ran and passed

`TestPassingValidator` searches recent history for real test commands and their paired outputs. No test run means fail. Non-zero exit means fail.

### 2. Diff is meaningful, not cosmetic

`DiffValidator` looks for git diff output and counts meaningful changed lines, excluding metadata and low-value noise.

### 3. Expected files exist

`FileExistsValidator` verifies explicit output files when provided, and can use constrained best-effort extraction when they are not.

This layer is not trying to prove mathematical correctness. It is enforcing a minimum reality threshold.

## Feedback Had to Be Machine-Actionable

When validation failed, Grinta did not just log a warning for humans.

It emits a structured error observation with:

- reason
- confidence
- missing items
- concrete suggestions

Then it returned the agent to `RUNNING` state and asked it to continue.

This turns validation from postmortem reporting into active steering.

## The "Force Finish" Escape Hatch

There is still a deliberate override: `force_finish`.

That existed because real workflows sometimes needed operator authority over strict gates.

The key is that it is explicit. Integrity is default; bypass is conscious.

## Why This Chapter Matters

People often ask why autonomous systems feel impressive in demos but unreliable in long-running work.

One major answer is simple: the demo agent is usually both worker and judge.

In Grinta, those roles were separated on purpose in the hard-gated design described here.

- The model proposes completion.
- The system verifies completion.
- Only then does finish become real.

That separation is boring, strict, and absolutely necessary.

## The Principle I Trust Now

If an agent can execute commands and edit your codebase, it cannot also be the final authority on whether the task is complete.

Not because models are useless, but because they are persuasive; and persuasive systems need independent verification.

---

## What Comes Next

The next chapter goes one layer deeper into execution governance: middleware order, rollback discipline, and why the pipeline contract matters as much as the model.

---

← [The Safety Sandbox Is Not Optional](21-the-safety-sandbox-is-not-optional.md) | [The Book of Grinta](README.md) | [The Middleware Contract](23-the-middleware-contract.md) →
