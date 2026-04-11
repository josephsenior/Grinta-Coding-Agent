# 21. Who Grades the Agent: The Completion Integrity Problem

Completion failures rarely start with bad code. They start with a believable narrative.

The model says: "Done."

The diff looks plausible. The tone sounds confident. The summary is clean. If you are moving fast, that is exactly the moment you want to believe it.

That moment is also where many systems fail, because an agent claiming completion is not evidence of completion.

## The Dangerous Version of "Success"

Early on, I treated finish as a procedural endpoint. If the model returned a finish action, the loop ended.

That sounds reasonable until you watch real sessions:

- tests were never executed
- important files were never written
- plan steps were still active
- the agent sounded decisive anyway

I learned the hard way that autonomous systems are naturally optimistic narrators. If you let them grade their own work, they will pass themselves too often.

## Finish Became a Gate, Not a Gesture

Grinta's task validation service changed the contract.

A finish action is now a request, not a verdict.

Before finish is allowed, the system can enforce multiple checks:

1. **Plan-state integrity:** if active plan steps still exist, finish is blocked.
2. **Validator availability integrity:** if completion validation is enabled but validator is unavailable, finish is blocked (fail closed).
3. **Task-result integrity:** validators must pass before the session can end.

That architecture removes the model's ability to "declare victory" without surviving external checks.

## The Plan-State Check Was a Big Deal

One of the strongest checks is also one of the simplest.

The validator walks the task plan tree and recursively finds non-terminal steps. If anything is still `todo` or `doing`, finish is blocked and the agent is pushed back into working state.

The feedback is explicit, not vague. The system reports which steps are still active and instructs the agent to update task tracking honestly.

That one guard eliminated an entire class of fake-finish behavior.

## Fail Closed, Not Feel Good

There is a policy decision in this subsystem that I care about deeply:

If completion validation is enabled and the validator is missing, Grinta blocks finish.

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

When validation fails, Grinta does not just log a warning for humans.

It emits a structured error observation with:

- reason
- confidence
- missing items
- concrete suggestions

Then it returns the agent to `RUNNING` state and asks it to continue.

This turns validation from postmortem reporting into active steering.

## The "Force Finish" Escape Hatch

There is still a deliberate override: `force_finish`.

That exists because real workflows sometimes need operator authority over strict gates.

The key is that it is explicit. Integrity is default; bypass is conscious.

## Why This Chapter Matters

People often ask why autonomous systems feel impressive in demos but unreliable in long-running work.

One major answer is simple: the demo agent is usually both worker and judge.

In Grinta, those roles are separated on purpose.

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

← [The Safety Sandbox Is Not Optional](20-the-safety-sandbox-is-not-optional.md) | [The Book of Grinta](README.md) | [The Middleware Contract](22-the-middleware-contract.md) →
