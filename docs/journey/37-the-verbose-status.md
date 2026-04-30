# 37. The Verbose Status

The chapter on observability (chapter 27) was about admitting the black hole existed. This chapter is about the small, unglamorous instruments I added once I stopped pretending I could debug an autonomous system by reading the transcript.

Three of those instruments matter enough to write down:

- **`/status verbose`** — a one-keystroke runtime diagnostics dump, surfacing the things you cannot see by watching the transcript.
- **Tracing opt-out env vars** — honest controls for users who do not want any out-of-process telemetry, ever.
- **In-band disconnect detection** — catching the case where the provider proxy injects an error message *as a streaming chunk* instead of closing the connection, which is the most insidious LLM failure mode I have hit.

None of these are intellectually thrilling. All of them have saved me hours.

---

## `/status verbose`

The original `/status` command was a courtesy: model name, autonomy level, cost, token count. Useful at a glance, useless when the agent felt off and you needed to know *why*.

`/status verbose` adds a diagnostics block that pulls from the actual subsystems instead of the cached HUD numbers. Every line is wrapped in defensive `try` / `getattr` so that a half-initialized controller (e.g. before the first turn, or right after a recovery) reports `n/a` instead of crashing the slash command. The block currently surfaces:

- **Circuit breaker state** — `closed` or `tripped`, with the consecutive error count and the rolling error rate. If the agent feels stuck, this is the first thing to look at: a tripped breaker means the runtime has already decided to back off.
- **Event stream queue depth** — pulled directly from the in-flight `asyncio.Queue`. Any non-trivial number here means events are being produced faster than subscribers are draining them, which is usually the early signal of an unrelated bug (a renderer that blocked, a delivery thread that fell behind).
- **Checkpoint count** — how many file-state snapshots the checkpoint manager is currently holding. Useful when “revert to last checkpoint” is not doing what the user expects.
- **Condensation events** — how many times conversation memory was condensed. If this is climbing fast, the model is hitting context pressure earlier than expected.
- **Cost / context tokens / LLM call count** — the same numbers as the HUD, but pulled from the same cached source so the verbose dump never disagrees with the on-screen totals.
- **Tracing state** — whether tracing is currently enabled, and which env-var opt-out is active. (More on this next.)

The discipline I tried to keep: every line is one fact, each fact is sourced from one place, and the line shows `n/a` when the source is genuinely missing rather than fabricating a zero. I have spent too many hours debugging metrics dashboards that confidently showed `0` for things that were actually unmeasured. `n/a` is honest. `0` is a lie disguised as data.

This is a CLI command, not a metrics page. It is meant to be read by a human in the moment they suspect the agent is misbehaving. The format is line-oriented, the keys are stable, and it can be grepped if a user pastes it into an issue. That is the entire design.

---

## Tracing Opt-Out Env Vars

The default tracing posture is conservative — telemetry is opt-out by default, and the only on-disk telemetry is the local audit logger. But “opt-out by default” is meaningless if there is no clean way to opt out, so the runtime now honors two env vars, in this order of precedence:

- **`DO_NOT_TRACK`** — the cross-tool community standard. If set to `1` / `true` / `yes` / `on`, all out-of-process tracing is suppressed regardless of any other setting.
- **`GRINTA_DISABLE_METRICS`** — the project-specific opt-out for users who want to disable Grinta tracing without touching `DO_NOT_TRACK` (which other tools also read).

Both are checked with the same case-insensitive matcher, both are surfaced in `/status verbose` as `opt_out_env=true`, and both override `TRACING_ENABLED=true` if it happens to be set. The asymmetry is deliberate: there is no env var that *forces* tracing on against a user’s explicit opt-out. Opt-out always wins.

Two principles I took from this:

1. **Honor the community standard before inventing your own.** `DO_NOT_TRACK` exists because users got tired of learning a new env var per tool. Adding `GRINTA_DISABLE_METRICS` is fine; making it the *only* opt-out would have been disrespectful to users who already set `DO_NOT_TRACK` everywhere.
2. **Make the opt-out visible from inside the program.** A user who set `DO_NOT_TRACK` six months ago should be able to confirm it is taking effect *right now*, not by reading the source. `/status verbose` shows the resolved state.

---

## In-Band Disconnect Detection

This one took longer to debug than I want to admit, because the failure mode looks like the model went insane.

When you stream from an LLM through a provider proxy — Lightning AI, OpenRouter, certain enterprise gateways — there is a specific failure mode where the upstream connection drops and the proxy, instead of closing the HTTP stream, *injects* an error message into the stream as if it were normal model output. The first chunk of the assistant message is something like:

> *“Upstream service unavailable. Please try again later.”*

…and then the stream closes cleanly. The HTTP layer is happy. The streaming layer is happy. The runtime treats it as the start of a real assistant turn and starts rendering. The user watches the agent confidently begin to explain that the upstream service is unavailable, then stop mid-sentence, and the runtime moves on to the next step convinced the model finished.

The fix is small: before the first chunk is yielded, accumulate a short prefix (capped at a handful of characters) and probe it against a list of known in-band disconnect phrases. If any phrase matches, the streaming path raises `APIConnectionError` with the prefix attached, and the retry layer picks it up the same way it would have if the connection had cleanly dropped. After the first chunk has yielded normally, the probe stops accumulating — once you have committed to streaming a real response, every subsequent chunk is real content, and the probe must not interfere.

A few constraints that mattered:

- **The probe is bounded.** Once the prefix exceeds `_INBAND_PREFIX_LIMIT`, the probe stops growing and the stream proceeds normally. A long legitimate first chunk should not be held hostage by a probe.
- **The phrase list is conservative.** Only patterns observed in the wild from real provider proxies. I refused to add speculative phrases, because a false positive turns a legitimate model response into a retry storm.
- **The error type is the same one the connection-level failure raises.** This is critical. The retry service already knows what to do with `APIConnectionError` (retry on transient connection failures, do not retry on rate-limit or service-unavailability). By raising the same exception, the in-band case inherits the same correct policy without the retry service needing to learn a new failure type.

This is the kind of bug you only ever notice once you have eyes on long sessions across multiple providers. It is also the kind of bug that, if you do not catch it, makes the model look unreliable when the provider was the actual unreliability. The fix is fifteen lines and a phrase list. The principle is bigger:

> **A streaming response that begins with words you would only hear from infrastructure is infrastructure pretending to be a model. Catch it before you start rendering.**

---

## What These Three Have In Common

They are all instruments that pay back their cost only on the bad day.

`/status verbose` is dead weight when the agent is healthy. It is the first thing you reach for when it is not, and the difference between *“breaker is tripped after 7 errors”* and *“something feels wrong”* is the difference between a five-minute fix and a one-hour archaeology session.

The tracing opt-out env vars are dead weight for users who have no privacy concerns. For the users who do, they are the difference between *“I trust this binary”* and *“I am about to delete it.”*

In-band disconnect detection is dead weight on every healthy stream. On the unhealthy ones — which are rare but reliably non-zero across long sessions — it is the only thing standing between *“the agent had one weird turn”* and *“the agent confidently hallucinated for the next six steps.”*

The pattern is consistent enough that I now treat it as a rule: **the most valuable instruments in an autonomous system are the ones that look like they are doing nothing 99% of the time.** If you optimize them out under the rationale that they are not pulling their weight, you are paying for that optimization with the worst hour of your year.

---

← [The Required Risk](36-the-required-risk.md) | [The Book of Grinta](README.md) | [The Vendor-Neutral Bench](38-the-vendor-neutral-bench.md) →
