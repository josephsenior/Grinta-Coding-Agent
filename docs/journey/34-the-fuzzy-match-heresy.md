# 30. The Fuzzy Match Heresy and the Death of Unified Diffs

> **Historical file API:** The `edit_symbol`-first facade below was later
> removed. The current write path uses `create_file`, `replace_string`, and
> atomic `multiedit`; `find_symbols` remains discovery-only. The match ladder is
> still part of the history that led to the smaller API.

There is a sentence I had to argue myself out of for months:

> *“If the agent cannot match an exact string, it is the agent's problem.”*

That sentence is satisfying. It is also the reason real edits used to fail half the time on real files. This chapter is the part of the journey where I gave up on exact-match purity, realized that **a tolerant editor is not a sloppy one — it is the one that survives indentation, line endings, and the realities of how LLMs serialize context**, and finally buried the unified diff.

---

## The Allure and Failure of the Unified Diff

When we designed Grinta, relying on standard unified diffs (`apply_patch`) felt like a no-brainer. Git uses them. Developers understand them. They are the universal language for representing edits. We thought: *Just tell the model to output a patch, and we apply it natively.*

But LLMs are not traditional UNIX command-line tools. They are next-token predictors. A unified diff requires strict, absolute mathematical correctness:
1. Exact line numbers (which shift dynamically as you edit the file).
2. Exact context lines preceding the change.
3. Exact whitespace matches.

We spent weeks layering heuristics on top of our `apply_patch` handler. We tried to find the `@@` headers dynamically if the file had drifted. We stripped and reduced spaces because models would often emit `+    def foo():` when it should have been `+  def foo():`. We appended verbose recovery tips in prompts, lecturing the LLM: *"You got the line numbers wrong, please re-read the file and try again."* We built a Circuit Breaker specifically for `apply_patch` because the model would stubbornly try the *exact same wrong patch* 5 times in a row, hallucinating different line numbers but never getting the context right.

Every patch we added to fix `apply_patch` just made the engine more brittle. The model was spending half its context window and reasoning budget trying to perform line-math, failing, refreshing the file, and inevitably failing again on large files.

### The Epiphany: Search-and-Replace Blocks

It turns out, LLMs are incredible at semantic pattern matching but terrible at counting. If you tell an LLM *"Find this exact block of code, and replace it with this new block"*, it can do that with extremely high fidelity. You don't need line numbers. You don't need `@@ -120,4 +125,5 @@`. You just provide the literal string.

We introduced exact replacement and AST-aware symbol editing. The success rate skyrocketed. Our agent stopped arguing with the parser and started writing code.

| Unified Diff Payload (Brittle, Line-Math Intensive) | Search-and-Replace Block Payload (Semantic, Reliable) |
|---|---|
| <pre>@@ -14,6 +14,7 @@<br> def process_data(data):<br>-    return data.strip()<br>+    if not data:<br>+        return ""<br>+    return data.strip()</pre> | <pre>&lt;&lt;&lt;&lt;&lt;&lt;&lt; SEARCH<br>def process_data(data):<br>    return data.strip()<br>=======<br>def process_data(data):<br>    if not data:<br>        return ""<br>    return data.strip()<br>&gt;&gt;&gt;&gt;&gt;&gt;&gt; REPLACE</pre> |

Today, the unified diff is dead. We tore out the `apply_patch.py` file, stripped the handler from `function_calling.py`, removed the circuit breakers, and purged it from the system prompts. We learned a valuable lesson: **Don't force an LLM to emulate a 1970s UNIX CLI tool.** Design the tools around the strengths of the LLM. String matching is native to language models; positional diffing is not.

---

## The Ladder of Match Modes

Even with search-and-replace blocks, exact match remains a lie in the real world. A tab vs. four spaces. CRLF vs. LF. A trailing space the user's editor stripped that the model still remembers. The model offered the right edit; the editor said no; the user blamed the model.

Grinta's default editor is now tolerant by construction, supporting three match modes in order of strictness:

### 1. `exact` — strict, byte-for-byte
Used when you genuinely care about every character: replacing a JSON literal, a regex pattern, a license header. The default for `view_range`-bounded edits where the model has *already* localized the change to a known span.

### 2. `normalize_ws` — general code edits (the default)
Before matching, both the haystack (file content) and the needle (search block) are normalized: tabs and spaces collapsed to a canonical form, trailing whitespace stripped on each line, CR/LF normalized to LF. The match still has to be unique after normalization. If the file uses tabs and the model offered spaces, the edit succeeds.

Crucially, **the file on disk is not normalized.** The output preserves the file's native line endings and indentation. The tolerance is only in the *match step*, not in the write step. That distinction is what kept this from turning into an automated whitespace-style war on every edit.

Here is the exact whitespace comparison function implemented in the editor:

```python
def normalize_whitespace(text: str) -> str:
    """Collapses multiple spaces/tabs to a single space, strips trailing characters, and normalizes line endings."""
    # Convert CRLF to LF
    unix_text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = unix_text.split('\n')
    
    normalized_lines = []
    for line in lines:
        # Strip trailing whitespace and collapse interior whitespace/tabs
        collapsed = ' '.join(line.split())
        normalized_lines.append(collapsed)
        
    return '\n'.join(normalized_lines).strip()
```

### 3. `fuzzy_safe` — bounded, single-anchor, last resort
Reserved for short snippets (≤120 characters) where the model knows the line it wants to change and one neighboring anchor line. The editor uses similarity scoring to relocate the target if it has drifted by a token or two. Two hard guard rails:
* **Single-line `old_str` only.** Multi-line fuzzy is how you get silent destruction of code.
* **Ambiguity rejection.** If the similarity scores of two candidates are within a small epsilon, the editor refuses. There is no “best guess.” There is found-uniquely or rejected.

---

## Non-Code Files Get a Different Protocol

Not all files are code. Markdown, YAML, JSON, plain text, `.gitignore`, `.env` templates. Tree-sitter does not have anything useful to say about most of them. Whitespace tolerance is *more* dangerous, not less, because YAML cares about indentation and Markdown cares about blank lines.

The robust edit protocol for non-code files added a smaller, simpler set of rules:
* **Show the line range you're editing.** The editor enforces a `view_range` discipline for the touch-points before the edit, so the model has to ground itself in current file state.
* **Preserve the file's native line endings, byte-for-byte.** A `.gitignore` written with CRLF stays CRLF. A YAML file written with LF stays LF.

The original protocol also included an optimistic-concurrency check: refuse the edit if the file had changed since the last read. That guard was removed. The strict hash check misfired too often — the user saving a file in their editor while the agent was thinking, or a build script touching a file, triggering a false conflict that derailed the edit flow. The lighter replacement is grounding through reads, tool observations, validation, and explicit failures only where they carry real signal. If a file changed between read and write, the model usually catches the mismatch through the edit response and re-reads. For the rare case where it does not, the tree-sitter validation post-edit catches structural damage. The guard that blocked before the edit was protecting against a threat that rarely materialized at the cost of frequent false positives.

---

## What I Refuse to Do

I want to be specific about lines I will not cross, because the appeal of more tolerance never goes away:
* **No multi-line fuzzy matching.** It is the single fastest way to delete code the user cared about.
* **No automatic re-indentation of model-supplied blocks.** The model knows what indent it wants. If it is wrong, the tree-sitter check catches it. If it is right, do not “help.”
* **No automatic conflict resolution against the disk.** If the file changed under us, the right answer is to fail loudly and let the agent re-read.
* **No silent format conversions.** No “auto-convert tabs to spaces because the project uses spaces.” That is an opinion. The editor does not get to have opinions.

Whitespace tolerance was built to remove a *false* failure (whitespace difference that doesn't change meaning). It was never to start guessing about *real* differences.

---

## Addendum: The Facade After the Fuzzy Match Era

Fuzzy matching improved edit reliability significantly, but it was not the final abstraction.

The real improvement came from a different direction: reducing the model-facing API. The raw editing block — any format where the model produces a structured payload that the backend must parse — was replaced by an intent-oriented tool facade. The model no longer constructs diffs, escapes strings, or manages open/close tags. It declares what it wants to do:

- `edit_symbol` for code, backed by tree-sitter and AST parsing.
- `replace_string` for grounded textual changes, with the three match modes as a fallback layer.
- `create` for new files and symbols.
- `multiedit` for atomic cross-file refactors.

The backend still uses normalization, AST parsing, rollback, and validation internally. The model no longer needs to think in editor protocols.

This layered design means the fuzzy-match modes are not the primary editing path anymore. They are the safety net. The primary path is `edit_symbol` — named symbol replacement with tree-sitter verification. When that does not apply (non-code files, generated code, templated languages), `replace_string` with its match modes takes over. And when the change crosses file boundaries, `multiedit` wraps everything in a transaction.

The match modes survived because they serve a real need. But the architecture stopped asking the model to think about them. The model just says "replace this symbol" or "find this string and change it." The backend handles the mode selection, the tolerance, and the validation.

That was the real lesson of the fuzzy match era: not that tolerance is the answer, but that the question itself changes when you stop asking the model to be an editor and start asking it to be a client of an editing API.

---

← [The Small Async Wars](33-the-small-async-wars.md) | [The Book of Grinta](README.md) | [The Self-Knowing Agent](35-the-self-knowing-agent.md) →
