# 32. The Required Risk

There is a particular failure mode I came to recognize on sight.

The model would call `execute_bash` with a perfectly reasonable command. The argument blob included `security_risk: "LOW"`. Or `security_risk: "low"`. Or `security_risk: null`. Or — most often — no `security_risk` field at all, because the model decided that field was *optional metadata*. The runtime accepted the call. The analyzer ran on its own and assigned its own risk label. The user never saw a confirmation prompt because the analyzer’s label was below the policy threshold. And then `rm -rf node_modules/` ran without asking.

The agent had not been malicious. It had not been clever. It had simply been allowed to *omit* the field that was supposed to be the safety gate. And every time we fixed a related class of issue elsewhere — better command analysis, tighter policy, smarter confirmation — this one stayed open, because the field was technically there in the schema and technically populated about 70% of the time, which is the worst possible reliability profile for a security primitive.

This chapter is about closing that gap and the surrounding cleanup it forced: making `security_risk` *required* at the schema level, collapsing autonomy to a single honest knob, and adding a per-session “always allow” memory so that mandatory confirmations did not become mandatory annoyance.

---

## Mandatory `security_risk`

The change is small in code and significant in posture. On every model-facing tool call that can inspect, execute, or mutate project state, the model must include a `security_risk` field with a value in `{LOW, MEDIUM, HIGH}`. Missing the field, sending an unrecognized value, or sending null all fail the tool call before it reaches the executor. The error that comes back to the model is structured and instructive: the field’s name, the allowed values, and the definition of each tier.

The system prompt’s `🔐 Security Risk Policy` section now states the rule in plain language and lists the three tiers with examples (LOW: read-only / scoped reads; MEDIUM: project-scoped edits or execution; HIGH: system-level or untrusted operations). It also tells the model two things that the schema cannot:

- The server runs an **independent analyzer** and may *escalate* a label, never lower it. The agent’s self-classification is the floor, not the ceiling.
- A HIGH escalation can require user confirmation. The agent should expect that and not retry around it.

That last clause matters. Earlier versions of the prompt left the impression that `security_risk: HIGH` was a *failure path* the agent should avoid. The new wording reframes it as an *honest path*: HIGH is what you say when an action is honestly high-risk, and the policy decides what to do with that label. Lying down to LOW to avoid confirmation is the worst possible behavior, because it bypasses the only signal the runtime trusts from the model.

The escalation policy itself sits in `command_analyzer` and `safety_validator`. It is not new. What is new is that it now has a reliable input: the schema-enforced label rather than a model-supplied wish.

---

## Why “Optional” Was the Bug

The deeper lesson here was about what *“optional security parameter”* means in an LLM context, and it is uncomfortable.

For a human caller, `security_risk: optional` is fine: the human will fill it in when it matters and leave it blank when it does not. For an LLM caller, *optional* is a coin toss. The same model on the same prompt with the same temperature will populate it 60% of the time on Tuesday and 80% on Wednesday. Worse, the population rate correlates inversely with the *risk* of the action — the model is more likely to fill in `security_risk` for a low-stakes `ls` than for a destructive `rm`, because destructive actions are usually the ones it generates under reasoning pressure where it cuts corners on schema completeness.

So an optional security gate is not a gate at all. It is a politeness request. The only honest options are:

- Make it required at the schema level and fail closed when missing.
- Remove the field entirely and let a server-side analyzer do all the labeling.

I went with required-and-fail-closed, because the model’s self-classification carries information the analyzer does not have — the *intent* of the call. The analyzer can tell that `git push --force` is high-risk. Only the model knows whether it is high-risk *in this turn’s context* (rewriting public history vs. cleaning up a personal feature branch). Throwing that signal away would have made the analyzer’s job harder.

---

## The Autonomy Collapse

The second change was overdue: autonomy modes used to differ in *behavior* across the whole stack, and most of the differences were lies.

The original three modes — `supervised`, `balanced`, `full` — branched in five places: the system prompt (different instructions per mode), the planner (different tool exposure), the retry service (different escalation thresholds), the cost cap loader (different `max_cost_per_task`), and the confirmation gate (different prompt frequency). On paper this gave the user fine-grained control. In practice it created cross-cutting bugs every time one of those branches drifted from the others, and a user who toggled `/autonomy balanced` mid-session would inherit a hybrid state where the prompt thought we were in `full` and the gate thought we were in `supervised`.

The collapse: autonomy is now a **single-axis knob** that controls *exactly one thing* — when the runtime stops to ask the user before running an action. That’s it.

- `conservative` (renamed from `supervised`): ask before every command, mutation, external tool call, terminal/browser action, or worker-coordination action in the confirmation flow.
- `balanced`: ask for high-risk or high-impact actions (where “high-risk” includes analyzer or model/tool labels of HIGH).
- `full`: never ask.

Execution is identical across modes. Prompting is identical across modes — the system prompt no longer branches on autonomy. Retry logic is identical. Cost caps and iteration limits were extracted into their own standalone config keys (`max_cost_per_task`, `warn_at_cost`, `max_autonomous_iterations`, `stuck_threshold_iterations`) with global defaults that apply universally regardless of mode.

Later, the `supervised` spelling was removed from config and the CLI entirely — only `conservative`, `balanced`, and `full` remain.

The whole rename took about an evening. Most of that time was deleting the per-mode behavior branches and convincing myself I was not *losing* a feature by doing so. I wasn’t. I was deleting a feature that had only ever been a bug surface.

---

## “Always Allow” Was Not a Convenience — It Was a Requirement

Once `conservative` mode actually meant *“ask before every action,”* the next problem appeared within five minutes of testing: every session became a parade of confirmation prompts for the same five commands. `pytest -q`. `git status`. `ls`. `cat README.md`. The user (me) was approving them so reflexively that the prompt had become noise, which is the definition of a security control degrading itself.

The `[y/n/a=always]` choice was the answer. `a` whitelists the *exact* action signature for the rest of the session, with a deliberately narrow definition of “signature”:

- For a shell command: the literal command string (`pytest -q` is whitelisted; `pytest -q --maxfail=1` is not).
- For a file action: the action type plus the path (`FileWriteAction:src/config.py` is whitelisted; `FileWriteAction:src/secrets.py` is not).
- For everything else: just the action type name.

Three rules I made non-negotiable:

1. **In-memory only.** The whitelist clears on process exit. There is no on-disk persistence. A user who chose `a` in one session is *not* committing themselves in the next session, because the threat model can change between runs.
2. **No fuzzy matching.** Exact signature equality. If the agent runs the same command with a different flag, it asks again. The signature is the contract; widening the signature widens the bypass.
3. **No automatic expansion.** Whitelisting `git status` does *not* whitelist `git`. Whitelisting `pytest -q` does *not* whitelist `pytest`. The agent has to ask the first time it tries each new shape.

The result is a confirmation gate that is annoying *exactly* as often as it should be: once per novel action per session. Repetition becomes silent; novelty becomes loud. That is the right trade.

---

## What This Chapter Is Really About

The patch is small. The shift is large.

Three principles I would defend in any code review:

1. **Security parameters that the LLM can omit are not security parameters.** Make them required at the schema, or move the responsibility entirely to the server side. The middle ground is a leak.
2. **Autonomy modes should differ in *one* observable behavior.** Every additional axis of variation is a future bug that you will pay for under load.
3. **A confirmation gate without a memory becomes noise.** Noise is a security degradation, not a security feature. The right memory is in-memory, exact-match, and per-session.

The composite effect is a system where the model has to be honest about risk, the runtime has *one* knob that controls how often it stops to ask, and the user is asked exactly often enough that the prompts still feel meaningful. That is the smallest amount of policy that survives real use, and the largest amount I am willing to defend.

---

← [The Self-Knowing Agent](35-the-self-knowing-agent.md) | [The Book of Grinta](README.md) | [The Verbose Status](37-the-verbose-status.md) →
