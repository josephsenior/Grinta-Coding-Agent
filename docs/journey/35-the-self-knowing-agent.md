# 31. The Self-Knowing Agent

Most of what looks like model misbehavior is actually the model lying to *itself* about what tools it has.

That sentence took me an embarrassing number of debug sessions to internalize. The model would shell out `Get-Command pylsp` to see if a language server existed, when the language server was already wired in and detectable through a single function call. It would call `read` six times in series when it could have batched safe read-only calls. It would describe condensation as “lossy summarization I should warn the user about,” when condensation in this codebase is automatic, middleware-driven, and free in turns and tool calls. It would say things like “let me check if I support multi-file edits” *to itself*, and then never check.

The model was confidently wrong about its own runtime. Not because it was a bad model. Because nothing in the system prompt told it the truth, and so it filled the gap with the average of its training data.

This chapter is about closing that gap. The fix has two halves: a **runtime-truth capability block** in the system prompt, and a set of **defaults that match what the prompt now claims is true** — parallel reads, atomic multi-edits, and provider-side parallel `tool_calls` wired through to the actual SDK call.

---

## The Capability Block

The first piece is a section in the system prompt called *“System Capabilities (verified at runtime).”* Every line in it is rendered from a live config flag or a runtime probe. Nothing in it is aspirational. If a default changes, the next prompt assembly reflects the change automatically.

The block currently teaches the model these facts:

1. Whether parallel tool scheduling is enabled in this run, and which read-only tools participate. The parallel-safe set is intentionally narrow: `read`, `find_symbols`, `grep`, `glob`, and `lsp` — read-only tools whose observation order does not matter.
2. Whether the provider supports emitting multiple `tool_calls` in a single assistant message (i.e. native parallel function calling at the API level).
3. Whether atomic multi-file edits via `multiedit` are exposed in this build. `multiedit` accepts `edit_symbols` and `replace_string` operations across files; it does not include `create`, which has separate atomicity requirements.
4. That conversation condensation is automatic, middleware-driven, costs zero turns, and uses a three-tier (working / episodic / semantic) memory model — *not* something the agent has to invoke or apologize for.
5. Whether checkpoint/revert is available for coarse rollback.
6. Which language servers and debug adapters were detected on `PATH`, with the explicit instruction: **do not shell out to `Get-Command`/`which`/`where` to rediscover this** — the line above is the authoritative answer.
7. Which MCP servers are active in the current session — the curated set (web search, web fetch, GitHub, quality gates, shadcn/ui, context7) is declared as runtime capabilities, not aspirational tool soup. The model knows they exist and can use them, but they are distinct from native core tools.
8. What mode the session is in — Chat, Plan, or Agent — and which tools are visible in each mode. The model should not see tools it should not use. `finish` and `communicate_with_user` are mode-aware.
9. Whether the Textual TUI is active. The model knows whether the user is looking at a rich terminal interface with HUD, cards, and mode switch, or a plain terminal.
10. Whether the quality gate before finish is enabled and whether it runs automatically on task completion.

The block ends with a sentence I care about: *“treat these as authoritative — do not contradict them in user-facing replies.”* That is not just style. The model would otherwise generate hedge phrases like *“I’m not sure if I can run those in parallel”* even when the block above the hedge said it could. Stating authority explicitly cut the hedging.

There is a small principle hiding here that I keep coming back to: **the prompt is a contract between the runtime and the model about what is true.** Most prompt engineering is about telling the model what to *do*. The capability block is about telling the model what *is*, which turns out to be the prerequisite for telling it what to do.

---

## Default-On Read Parallelism

Once the capability block was honest, the next problem was that one of the things it would honestly say was *“parallel scheduling is OFF in this run.”* Which the model would then dutifully obey — issuing reads sequentially even when the task obviously wanted them parallel.

So the default flipped. `enable_parallel_tool_scheduling` is on by default, and the parallel set is intentionally narrow: `read`, `find_symbols`, `grep`, `glob`, and `lsp`. Every one of these is read-only. None of them touches disk in a way that another concurrent call could race against.

What is *not* in the parallel set is just as deliberate: shell commands, file edits, file writes, `create`, `edit_symbols`, `replace_string`, `multiedit`, terminal_manager I/O. Anything that mutates state runs sequentially, full stop. The chapter on parallelization went through *why* (chapter 25 — “The Parallelization Trap”). This chapter is about how the boundary survived being crossed under pressure, because the moment you turn parallel reads on by default, every PR that adds a new read-style tool comes with a thirty-second internal argument about whether to add it to the parallel allowlist. The answer has to be a structured one: only if the tool is genuinely read-only, only if its observation order does not matter, only if it cannot fail in a way that contaminates the others. That gate is small but real.

The result, on long sessions, is unmistakable. A turn that used to be six sequential `read` calls now becomes one assistant message with six `tool_calls` resolved concurrently. The wall-clock saving is meaningful. The token saving is even larger, because the model no longer has to write six “let me read the next file” preambles between calls.

---

## `parallel_tool_calls` Has to Reach the SDK

This was the unglamorous part. The capability block said *“provider-side parallel function calls: enabled”* — but the provider SDK call still emitted one `tool_call` at a time, because the kwarg was never actually passed through.

The fix lives in `backend.inference.catalog_loader`. Each model entry in the catalog carries a `supports_parallel_tool_calls` flag. The sanitizer that builds final SDK call kwargs reads that flag and, when the model supports it and the caller has not explicitly disabled it, injects `parallel_tool_calls=True` into the kwargs before the SDK is invoked. The Gemini mapper has its own pass that strips the kwarg cleanly when routing to the native Google SDK (which does not accept it). One catalog flag, one sanitizer pass, one mapper-level strip — and the prompt’s claim is no longer aspirational.

The pattern matters more than the kwarg. **Every line in the runtime-truth block must have a *receipt* somewhere in the runtime.** If the block says “parallel tool_calls are enabled,” the kwarg has to actually land in the SDK call. If the block says “LSP server `pylsp` is available,” the planner has to actually expose `lsp` for that language. If the prompt and the runtime drift, the model trusts the prompt, the runtime trusts the code, and the user gets stuck in the gap.

---

## Atomic Multi-File Edits as a First-Class Capability

The third piece is `multiedit`. Before it existed, the agent would do a refactor across five files as five sequential exact replacements or symbol edits. If the third call failed — uniqueness mismatch, syntax error caught by the tree-sitter middleware, anything — the first two had already landed and the last two had not. The repository was now in a half-refactored state, the agent had no clean rollback path, and the only honest recovery was to checkpoint-revert the whole turn (assuming checkpoints were enabled, which they often were not on lower-power configurations).

`multiedit` is one tool call that takes a list of `edit_symbols` and `replace_string` operations across files and treats the batch as a transaction. `create` is deliberately excluded — batch creation has different atomicity semantics and is handled through individual `create` calls or a dedicated batch creation path. Every file commits or none do. On the first failure — uniqueness mismatch, parse error, write error, anything — the previous writes in the batch are rolled back from in-memory snapshots before any observation is returned to the model. The model never sees a half-applied state.

This is the kind of feature that sounds boring on a slide and is load-bearing in practice. Cross-file refactors are common. Half-applied refactors are catastrophic, because the model now has to re-derive *which* files it already touched and which it did not, and it does that by re-reading every file, and the context budget collapses.

The capability block teaches the model that `multiedit` exists in this build (or doesn’t — the sentence varies based on the build). Unlike the other capability lines, this one came with a fallback sentence for builds where it is not exposed: use smaller `replace_string` or `edit_symbols` calls and take a `checkpoint` before the batch for coarse rollback. That fallback is not a consolation prize. It is the second-best honest answer, and the agent needs to know what it is when the first-best answer is unavailable.

---

## Why I Wrote This Chapter

The biggest single quality jump in the agent over the last month did not come from a smarter planner or a richer toolset. It came from the model finally knowing what it had, with the same confidence the runtime knew it.

Three principles I would carry into any future agent:

1. **Capability statements are runtime-derived, never authored.** The moment a human writes “the agent supports parallel reads” into a prompt, the moment that prompt outlives the feature, the model lies on the runtime’s behalf.
2. **A capability statement without a runtime receipt is worse than no statement.** It teaches the model to trust a falsehood. Better to delete the line than to leave it pointing at a kwarg that never reaches the SDK.
3. **Defaults must match the capability story.** If parallel reads are honestly available, they should be on by default. If atomic multi-edits exist, they should be the recommended path for cross-file change. The capability block is a *promise*; defaults are how the promise is kept on the runtime side.

The rest is plumbing — a sanitizer here, a mapper-level strip there, a runtime probe for LSPs and DAPs. None of it is intellectually exciting. All of it is what makes the model stop hallucinating about its own body.

---

← [The Fuzzy Match Heresy and the Death of Unified Diffs](34-the-fuzzy-match-heresy.md) | [The Book of Grinta](README.md) | [The Required Risk](36-the-required-risk.md) →
