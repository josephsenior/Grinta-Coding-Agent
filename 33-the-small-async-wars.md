# 29. The Small Async Wars

Most of the bugs that nearly broke this project did not come from the model. They came from the half-second between two `await` points where I assumed the world stood still.

This chapter is the addendum I owe to the chapters on reliability. The big stories — circuit breakers, stuck detection, completion integrity, crash recovery — have their own homes. What I never wrote down is the smaller, more embarrassing layer: five specific async / state-machine fights that each took longer than they should have, each shipped a single small fix, and each closed a class of failure that would otherwise have looked like the *model* misbehaving.

I want to put them on the record together because the lesson generalizes. **In an autonomous system, the difference between “the agent went insane” and “the agent encountered a half-second race condition” is invisible from the transcript.** The model gets blamed for the runtime’s mistakes more often than I would like to admit.

---

## 1. The NullAction Hot Loop

The first one was the cheapest to write and the most expensive to find.

`NullAction` is a sentinel the agent emits when there is nothing to do this turn — a thinking pause, an internal observation, a no-op that the runtime needs to acknowledge but does not need to execute. Useful, lightweight, designed to be ignored.

What I had not noticed is that the step loop — `astep` → action arrives → `NullAction` → schedule next step — had no friction in the null case. A `NullAction` was emitted, observed, and immediately triggered another `astep`. The stuck detector ignored null events on principle (they are not real actions). Cost tracking ignored them too. From the outside, the agent looked busy. The HUD showed a spinner, the call counter ticked up, and tokens evaporated at full speed. From the inside, the model was politely saying *“nothing to do”* on a tight loop and the runtime was politely calling back asking *“sure?”* a few hundred times a minute.

The fix is unceremonious: `ActionExecutionService` now caps consecutive `NullAction`s at three, then transitions to `PAUSED` with a structured reason of `NULL_ACTION_LOOP`. The pause is loud — it shows up in `/status verbose`, in the audit log, and in the next user prompt — so the operator knows what happened instead of inheriting a session that *felt* unresponsive.

The principle I took out of this: **every loop in the runtime needs a non-trivial floor.** If a loop can repeat with zero observable effect, it will, and the most dangerous version is the one that looks like real work.

---

## 2. The StepGuardService Grounding Gate

The second one was the bug that made me stop trusting the model’s post-edit confidence.

Pattern: the agent edits a file. The auto-check middleware reports a tree-sitter syntax error or a failing test. The agent reads the failure, *immediately* writes another edit to the same file based on its memory of what it just changed, and the second edit makes things worse because the model never re-read the file after the failure. Three turns later the file is unrecognizable and the agent is debugging a bug that no longer exists at the line it thinks it does.

The model was not being lazy. It was being *fast*. It had a perfect mental model of the edit it had just made, and it skipped the re-read because it “knew” what was there.

The fix landed in two layers:

- `StepGuardService` watches for the pattern *“recent file mutation followed by failing feedback”* and sets a flag — `__step_guard_verification_required` — on the agent state.
- `ActionExecutionService` checks that flag before scheduling the next write or finish action. If the flag is set, more writes and the `finish` tool are blocked until the agent performs one *grounding* action: a read, a search, a check, a terminal command that produces real evidence.

Crucially, this is **runtime enforcement, not prompt instruction.** I tried the prompt version first — a sentence in the system prompt asking the model to re-read after a failed edit. It worked maybe 60% of the time, which is the worst possible reliability profile for a correctness gate. Pushing the rule into the runtime made it 100%, at the cost of one extra forced read every time the pattern triggered. That trade is worth it on the bad day and invisible on the good one.

---

## 3. The Cumulative-Resend Tool-Call Bug

This one I want to write down because it is the kind of bug that exists *only* because the LLM streaming protocols are not standardized.

Different providers ship streaming tool-call fragments differently. Some send pure deltas: each chunk is the *next* slice of the function name and arguments, and the runtime concatenates. Others send cumulative re-sends: each chunk is the *full* function name and arguments so far, growing each time. A few do both within a single stream — deltas at first, then a cumulative resend at the end as a sanity flush.

The naive merger in `executor.py` was `+=` concatenation. Which works perfectly for pure-delta providers, and produces results like `analyze_project_structureanalyze_project_structure` for cumulative-resend providers. The user sees a tool call to a function that does not exist, the dispatcher rejects it, the agent retries, the *next* stream resends cumulatively too, and the function name doubles again on the retry. I have screenshots of `analyze_project_structureanalyze_project_structureanalyze_project_structure` from a particularly enthusiastic stream.

The fix is overlap-aware merge semantics:

- If the incoming chunk is a *prefix* of the existing buffer, ignore it (we already have more).
- If the existing buffer is a *prefix* of the incoming chunk, replace (cumulative resend supersedes).
- If neither, look for a suffix-of-existing / prefix-of-incoming overlap and merge there.
- For arguments specifically, treat balanced JSON braces / brackets as a structural extension hint — a chunk that closes the current JSON tree replaces rather than concatenates.

This now lives behind a regression test (`test_async_execute_handles_cumulative_tool_call_name_and_args`) that captures the exact failure shape. The test is intentionally ugly. The bug it covers is intentionally specific. Both should stay that way.

The principle: **never concatenate streamed protocol fragments without considering that the protocol may be cumulative.** The cost of overlap-aware merging is one string comparison per chunk. The cost of being wrong is the model looking insane.

---

## 4. The Tail-Call Race

This one is short and I am only writing it because it bit me twice.

`SessionOrchestrator._step_inner()` ends, in the happy path, by tail-calling `self.step()` to schedule the next turn. That is normally fine. But `_step_inner()` also produces events — observations, state changes — and those events go through `_on_event` routing on a *background* task. One of the things `_on_event` can do is flip the agent state to `AWAITING_USER_INPUT` (e.g. when the model emits a `MessageAction` that asks the user a question).

Race: `_step_inner()` finishes. It tail-calls `self.step()`. The background `_on_event` has not yet flipped the state. `step()` reads the state as still `RUNNING`, schedules another turn, and only *then* does the background flip land. The agent appears to pause (the message is shown, the state goes `AWAITING_USER_INPUT`) and then immediately keeps going on the requeued step.

The fix is one line of patience: yield to the event loop once before the tail requeue, then re-check state. If the background flip landed in that window, the requeue is skipped. If it did not, the original behavior is preserved. One `await asyncio.sleep(0)` and a state re-check.

Two principles, both of which I will probably re-learn:

1. **Tail-calls inside an async loop are not free.** They run before pending background tasks have had a chance to settle. If those background tasks own state-machine transitions, your tail-call can race them.
2. **State machines need *one* authority on transitions.** When the routing layer can flip state and the orchestrator can read state, the orchestrator must always re-check after yielding.

---

## 5. The Checkpoint Handoff That Looked Like a Crash

The last one is a UX-correctness story disguised as a state-machine fix.

`checkpoint` and `revert_to_checkpoint` are tool calls. Like every tool call, they can succeed, fail, or land in an awkward intermediate state — for example, a `revert_to_checkpoint` that finds the checkpoint is missing because cleanup ran between the snapshot and the restore. Early on, that intermediate state was surfaced as an `ErrorObservation`, because the runtime could not silently swallow it.

The problem: an `ErrorObservation` looks like a *runtime crash* in the UI. The CLI shows a red panel, the user’s heart rate goes up, and the agent — who actually has a perfectly reasonable next move (take a fresh checkpoint, retry the operation, fall back to manual edits) — cannot self-heal in the same turn because the user is now staring at a scary message asking what to do.

The fix is to route incomplete checkpoint handoffs through `state.set_planning_directive` instead. The directive is invisible to the user. It tells the *next* model step what happened (“checkpoint X was unavailable; consider re-snapshotting before risky writes”). The agent reads it, picks a sensible recovery, and the user sees one clean activity card instead of an error panel followed by a recovery attempt.

The general rule I want to remember: **internal-tool intermediate states should steer the next step, not surface as user-visible errors.** A real crash is an `ErrorObservation`. A correctable handoff is a planning directive. Mistaking the second for the first is how a self-healing system loses the trust of its operator.

---

## A Note on `sandboxed_local` While I Have the Floor

Closely related to all of the above, there is one piece of operational honesty that belongs here rather than in chapter 21 (the Safety Sandbox chapter), because it lives at the same async / runtime boundary.

`sandboxed_local` is the optional execution profile that isolates non-interactive subprocess commands using OS-native sandboxing — Windows AppContainers on Windows 10+, equivalents elsewhere. The intent is clear: a `pytest` run or an `npm install` runs in a low-integrity child process that cannot reach outside the workspace.

What is *not* claimable, and what I refuse to overstate:

- The launcher works on Windows for `cmd`-style commands. Direct AppContainer launch, low-integrity child token, the whole story. PowerShell built-ins inside the sandbox are still **degraded** — some cmdlets behave differently under the integrity level. Do not claim full Windows PowerShell parity under `sandboxed_local`. I do not, and the prompt does not.
- Two pitfalls cost me a weekend: `os.set_handle_inheritable()` must receive raw Win32 handles from `msvcrt.get_osfhandle()`, *not* CRT file descriptors; and `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` must use the official value `0x00020009` or `UpdateProcThreadAttribute` fails with `WinError 50`. These are not in the documentation paths most people land on. They are receipts I am leaving here in case someone reproduces the work.
- **Interactive terminal sessions stay unsandboxed even under `sandboxed_local`.** The capability and latency cost of running an interactive PTY through an AppContainer is too high, and the threat model is different — the user is in the loop. If the PTY backend is unavailable on a given platform, tmux remains an allowed interactive fallback.

This is the same posture as the rest of the safety story: be specific about what is enforced, be specific about what is not, and never let the marketing version of a feature outrun the implementation.

---

## Why This Chapter Exists

None of the five fixes in this chapter is impressive in isolation. They are roughly fifty lines of code total, scattered across five files, behind regression tests that nobody else will ever read. They are the kind of work that does not show up in release notes because they are framed as “fix: stabilize step loop” and the diff is small.

But every single one of them was a multi-day debugging session disguised as a one-line patch, and every single one of them was initially diagnosed — by me, in real time — as the *model* doing something wrong. The model was not. The runtime was. The async layer between the model and the world had a tiny correctness gap, and the gap was filled by the model’s output being misread.

If you build agents, save yourself a week: the next time the model looks like it is hallucinating, behaving erratically, or giving up too fast, **check the loop, the streaming merger, the state machine, and the event timing first.** The model is the easiest thing to blame and almost never the actual culprit.

---

← [The Two Lives of the Terminal](32-the-two-lives-of-the-terminal.md) | [The Book of Grinta](README.md) | [The Fuzzy Match Heresy and the Death of Unified Diffs](34-the-fuzzy-match-heresy.md) →
