# 34. The Fuzzy Match Heresy

There is a sentence I had to argue myself out of for months:

> *“If the agent cannot match an exact string, it is the agent’s problem.”*

That sentence is satisfying. It is also the reason real edits used to fail half the time on real files. This chapter is the part of the journey where I gave up on exact-match purity and accepted that **a tolerant editor is not a sloppy one — it is the one that survives indentation, line endings, and the realities of how LLMs serialize context.**

The dirtiest secret in this whole project is that *exact match is a lie even when both strings look identical.* A tab vs. four spaces. CRLF vs. LF. A trailing space the user’s editor stripped that the model still remembers. A no-break space copy-pasted from documentation. The model offered the right edit; the editor said no; the user blamed the model.

So I went heretical. The default editor is now tolerant by construction, and the tolerance has a small ladder of well-defined modes. I want to write down what those modes are, why they exist, and what guard rails I added so that “tolerant” did not slide into “wrong.”

---

## The Failure Mode That Forced the Issue

I was running the agent on a Windows checkout of a project that had been edited on Linux. The file had mixed `\n` and `\r\n` endings — common, ugly, real. The agent read three lines around a function it wanted to change. Everything in its reasoning trace was correct. The `replace_text` call used the exact substring it had just read.

The editor rejected it. *Substring not found.*

The user (me) had to step in, normalize line endings by hand, re-run the edit. The model had done nothing wrong. The editor had done nothing wrong *by its own contract*. The contract itself was wrong for the world it had to live in.

That is when the policy changed: **match-mode is a first-class parameter, the default is a forgiving one, and strict-exact is opt-in for the cases that demand it.**

---

## The Ladder of Match Modes

There are three modes, in order of strictness, each with a real reason to exist.

### `exact` — strict, byte-for-byte

Used when you genuinely care about every character: replacing a JSON literal, a regex pattern, a license header. The default for `view_range`-bounded edits where the model has *already* localized the change to a known span. Strict-exact is still the safest mode for *generated* code — anything where the model just produced the surrounding context itself and should not be allowed to lie to itself about it.

### `normalize_ws` — the new default for general code edits

This is the one that earned its place. Before matching, both the haystack and the needle are normalized: tabs and spaces collapsed to a canonical form, trailing whitespace stripped on each line, CR/LF normalized to LF. The match still has to be unique after normalization. If the file uses tabs and the model offered spaces, the edit succeeds. If two normalized matches exist, the editor refuses with a helpful error rather than picking one.

Crucially, **the file on disk is not normalized.** The output preserves the file’s native line endings and indentation. The tolerance is only in the *match step*, not in the write step. That distinction is what kept this from turning into an automated whitespace-style war on every edit.

### `fuzzy_safe` — bounded, single-anchor, last resort

Reserved for one specific case: short snippets (≤120 characters) where the model knows the *line* it wants to change and one neighboring anchor line. The editor uses similarity scoring to relocate the target if it has drifted by a token or two. Two hard guard rails:

- **Single-line `old_str` only.** Multi-line fuzzy is how you get silent destruction of code you did not intend to touch.
- **Ambiguity rejection.** If the similarity scores of two candidates are within a small epsilon, the editor refuses. There is no “best guess.” There is found-uniquely or rejected.

`fuzzy_safe` is *off* by default. The agent can pass `match_mode: fuzzy_safe` when it has read the file and knows what it is doing. Most edits never need it. The ones that do — minor anchor drift after a previous edit in the same turn — would otherwise fail with a frustrating “substring not found” when the substring was *almost* there.

---

## The Whitespace Truth Nobody Likes

I tried, briefly, to make `normalize_ws` smart enough to handle the most painful cases on its own: re-indenting the inserted text to match the surrounding block, trimming trailing newlines that the model added for cosmetic reasons, padding the inserted block when the line above had a trailing line ending the model forgot.

I rolled most of that back. Not because it did not work — it did, in isolation. But because *every silent transformation widens the gap between what the model thinks it wrote and what the file actually contains.* The next edit, the next turn, the model reads the file again and finds something that does not match its memory. The agent then second-guesses its earlier edit. You get a loop of “I thought I changed this” reasoning that costs context and confidence.

The compromise I landed on: **match-time tolerance is generous, write-time transformation is conservative.** Whitespace normalization decides whether a match exists. The file on disk reflects exactly what the model said to write, with the file’s native line ending appended only when inserting non-newline text into a non-empty file (otherwise lines silently concatenate, which was its own bug class). That single rule eliminated a whole category of “my insert created a syntax error two functions away” reports.

---

## Tree-sitter as the Receipt

Tolerance is fine until the day it is not. The day it is not is the day the agent edits a Python file, the syntax breaks, and three turns later the agent is debugging a runtime error that does not exist because the source no longer parses.

So every successful edit on a supported language passes through a **tree-sitter syntax check** before the observation goes back to the model. The check lives in the auto-check middleware, not in the editor itself, which matters: middleware is the layer where every action has to walk past on its way out of the runtime, so there is no editor variant — `replace_text`, `insert_text`, `multi_edit`, `create_file` — that can sneak past it.

If the post-edit AST contains an `ERROR` or `MISSING` node, the observation that comes back to the agent is not “edit applied successfully.” It is a structured warning with the exact line, column, and a 60-character snippet of the broken region. The agent sees the receipt the same turn it made the edit. No silent corruption.

Two design notes that took longer to land than I want to admit:

- The check operates on the **content the editor was about to write**, not on the file re-read from disk. In sandboxed runtimes the file may not exist on the host at all, and a re-read would fail spuriously. Pass the bytes; never trust the path.
- The check is **language-aware via file extension only.** No magic. If the extension is not in `LANGUAGE_EXTENSIONS`, the middleware shrugs and lets the edit through unchecked. Better silent on unknown languages than wrong on known ones.

I treat the tree-sitter pass as the *final* contract test of the edit pipeline. Whitespace tolerance widened the front door. Tree-sitter narrowed the back door. The middle — find the unique target, replace it with the model’s string, write to disk — stayed boring.

---

## Non-Code Files Get a Different Protocol

The other half of the editing story I had been quietly ignoring: not all files are code. Markdown, YAML, JSON, plain text, `.gitignore`, `.env` templates, configuration files. The model edits these constantly. Tree-sitter does not have anything useful to say about most of them. Whitespace tolerance is *more* dangerous, not less, because YAML cares about indentation and Markdown cares about blank lines.

The robust edit protocol for non-code files added a smaller, simpler set of rules:

- **Show the line range you’re editing.** The editor enforces a `view_range` discipline for the touch-points before the edit, so the model has to ground itself in current file state, not in a stale memory.
- **Refuse the edit if the file changed since the last read in this turn.** This is a soft optimistic-concurrency check, not a transactional lock. It is enough to catch the “the user just saved the file from VS Code while the agent was thinking” cases.
- **Preserve the file’s native line endings, byte-for-byte.** A `.gitignore` written with CRLF stays CRLF. A YAML file written with LF stays LF. The editor does not have an opinion about which is right.

None of this is glamorous. It is the layer that separates an agent that edits files in a demo from one that edits files in a project a human is also editing.

---

## What I Refuse to Do

I want to be specific about lines I will not cross, because the appeal of more tolerance never goes away.

- **No multi-line fuzzy matching.** It is the single fastest way to delete code the user cared about. The cost-benefit is permanently negative.
- **No automatic re-indentation of model-supplied blocks.** The model knows what indent it wants. If it is wrong, the tree-sitter check catches it. If it is right, do not “help.”
- **No automatic conflict resolution against the disk.** If the file changed under us, the right answer is to fail loudly and let the agent re-read. Three-way merging belongs in `git`, not in a tool call.
- **No silent format conversions.** No “auto-convert tabs to spaces because the project uses spaces.” That is an opinion. The editor does not get to have opinions.

The whole point of fuzzy match modes was to remove a *false* failure (whitespace difference that doesn’t change meaning). It was never to start guessing about *real* differences.

---

## Why This Chapter Matters

The boring conclusion of this chapter is that the editor — the single most-called tool in the entire system — is now ~200 lines of matching policy and a tree-sitter call. The interesting conclusion is that getting to those 200 lines required deleting a lot of cleverness.

If you build coding agents, you will face the same temptation. The model will produce *almost-right* edits. You will be tempted to make the editor smart enough to interpret intent. Resist that temptation past `normalize_ws`. The right escape valve is a richer error message back to the model — “found 0 matches; did you mean line 47?” — not a more creative parser.

The model is the creative one. The editor is the receipt printer.

---

← [The Patch That Refused to Die](33-the-patch-that-refused-to-die.md) | [The Book of Grinta](README.md) | [The Self-Knowing Agent](35-the-self-knowing-agent.md) →
