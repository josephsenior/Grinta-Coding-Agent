# 40. The Facade Pattern and the Smaller File API

There is a moment in systems engineering where you realize the complexity is no longer in the code itself, but in the interface you are forcing the user to navigate.

For Grinta, the user is the model.

The current editing facade keeps the backend responsible for path safety, AST location, validation, diffs, and atomic commits, while the model sees only a small intent-oriented API:

- `read`
- `find_symbols`
- `create`
- `edit_symbol`
- `replace_string`
- `multiedit`

The rule is now simple: read may search, write must target. The model does not choose a transport format or editor mode. It chooses whether it needs context, a new file or symbol, a symbol edit, an exact string replacement, or an atomic multi-file refactor.

The backend keeps its structural machinery. The prompt keeps one clear mental model.

---

## What the Chapter Title Does Not Say

This chapter was originally framed as an escape from a specific transport format — JSON escaping hell, XML as the savior. That framing was wrong. Not because JSON vs XML is unimportant, but because the format was never the root problem.

I tried JSON for structured tool output. The model kept leaking escape sequences into the content, producing malformed blocks that the parser could not recover from.

I tried XML as the replacement. The model kept leaking JSON escape behavior into XML blocks, because the underlying model had been trained on so much JSON-formatted tool use that the escape behavior was baked into its weights.

I tried raw text blocks without any wrapping format. The model lost the boundary between tool output and conversational text.

None of these failed because of the format. They failed because I kept giving the model a transport-format job at all. Every format placed the model in the role of a serialization engineer — balancing brackets, escaping quotes, tracking nesting depth — when the model should have been thinking about code.

The fix was not choosing JSON, XML, shell, or raw text.
The fix was removing transport-format thinking from the model's job entirely.

---

## The Raw Editing Block Died

Before the facade, the model produced structured editing blocks wrapped in a transport format. The flow was: model generates JSON/XML → parser extracts the edit → backend applies it.

The problem was not the parser. The problem was that every transport format leaked.

JSON leaked because the model could not reliably produce valid JSON containing code that itself contained quotes, backslashes, or special characters. The escape sequences nested. The model lost track of which level of escaping it was on.

XML leaked because the model treated it like JSON-with-angle-brackets. It would produce malformed CDATA sections, forget to close tags, or — most subtly — apply JSON escape rules inside XML content. The underlying model's training on JSON-heavy tool use was so deep that the escape behavior transferred.

Raw text blocks leaked because without delimiters, the model could not reliably separate its reasoning from the edit payload. The boundary between "what I am about to do" and "here is the edit" blurred.

Each format felt like progress for a week. Each format failed within a month.

The raw editing block — any format where the model produces a structured payload that the backend must parse — had to die. Not because of implementation bugs. Because the architecture was asking the model to do something it is fundamentally bad at: acting as a serialization library.

---

## The New Rule: Read May Search, Write Must Target

The facade replaced the editing block with a single rule: **read may search, write must target.**

Read operations are allowed to be fuzzy. When the model calls `read`, the backend can resolve paths, search for symbols, find the right file. The model is asking for context, and the backend should make that easy.

Write operations must be explicit. The model must name the file, name the symbol, or provide the exact string. The backend does not guess where the edit goes. If the model cannot identify the target precisely enough, the write fails.

This asymmetry is deliberate. Reads benefit from flexibility — the model often knows what it needs but not exactly where it lives. Writes need precision — a wrong guess can corrupt a file silently.

The rule manifests differently in each tool:

| Tool | Read-side behavior | Write-side behavior |
| --- | --- | --- |
| `read` | Auto-resolve file paths, accept symbol names, return symbol contents | N/A — read only |
| `find_symbols` | Accept partial names, return all matches with locations | N/A — read only |
| `create` | N/A | Must name the file and provide full content |
| `edit_symbol` | Accept symbol names for location | Must provide the new body for a named symbol; no wildcard matching |
| `replace_string` | N/A | Must provide exact old and new strings |
| `multiedit` | N/A | Each sub-edit must meet its own write rule |

The model never has to guess where a write lands. If it does not know the target, it calls `read` first. That is the flow: read to discover, then write with certainty.

---

## The Final Editing Surface

Six tools. Each one exists because the others could not cover its use case cleanly. Each one has a deliberate boundary where it stops and the next tool takes over.

### `read` — Get Context

Takes a file path, optionally a line range or symbol name. Returns file content.

**Design decisions:**
- If the model passes a symbol name instead of a path, the backend searches for the symbol and returns its source. If exactly one file contains it, the content is returned directly. If multiple files contain it, candidates are listed and the model must pick a path.
- `read` is the only tool allowed to do implicit search. Once the model has read, it is expected to write with explicit targets.

### `find_symbols` — Explore Structure

Takes a file path, optionally a symbol name filter. Returns a list of symbol names, kinds, and locations.

**Design decisions:**
- Purely structural. No file content returned. If the model needs content, it calls `read` with the symbol name.
- Uses tree-sitter behind the scenes. If tree-sitter is not available for the language, falls back to regex-based symbol extraction.

### `create` — New Files or Symbols

Takes a file path and content. Creates the file if it does not exist.

**Design decisions:**
- Does not overwrite existing files. If the file exists, the model must use `edit_symbol` or `replace_string`.
- `create` is deliberately not part of `multiedit`. Batch creation has different failure semantics from batch editing, and conflating them would complicate atomicity guarantees.

### `edit_symbol` — Targeted Symbol Changes

Takes a file path and a list of symbol edits. Each edit names a symbol (function, class, method) and provides the new body.

**Design decisions:**
- The symbol must exist. `edit_symbol` does not create new symbols — that is `create`'s job.
- Writes must be explicit. The model names the symbol; the backend finds it via tree-sitter and replaces the body. No path guessing, no content-based search.
- If tree-sitter is not available, `edit_symbol` degrades gracefully but prefers `replace_string` as an alternative.
- AST tools are the preferred path for code. `edit_symbol` is the primary code editing tool. `replace_string` exists for the cases where AST does not apply.

### `replace_string` — Grounded Text Replacement

Takes a file path, an old string, a new string, and an optional match mode (`exact`, `normalize_ws`, `fuzzy_safe`).

**Design decisions:**
- This is the general text fallback. Not just for non-code files — also for generated code, templated languages, or any case where AST-based editing is overkill or unavailable.
- The old string must be unique (or the match mode must disambiguate). If it matches multiple locations, the edit is rejected. The model must narrow the scope by reading a smaller range.
- Supports the three match modes from the fuzzy-match chapter: exact (byte-for-byte), normalize_ws (whitespace-tolerant), and fuzzy_safe (single-line, similarity-scored, last resort).
- Multi-string replacement is handled by calling `replace_string` multiple times, or by using `multiedit` for atomic cross-file changes.

### `multiedit` — Atomic Multi-File Refactoring

Takes a list of `edit_symbol` and `replace_string` operations across multiple files. Applied as a single transaction.

**Design decisions:**
- Every write commits or none do. On the first failure — uniqueness mismatch, parse error, write error — previous writes in the batch are rolled back from in-memory snapshots before any observation is returned to the model. The model never sees a half-applied state.
- `multiedit` does not include `create` operations. Batch creation has different atomicity requirements and is handled separately through individual `create` calls or a dedicated batch creation path.
- Cross-file refactors are the primary use case. Renaming a function across five files, changing a return type across a module boundary, updating error messages consistently.
- The model must still name explicit targets for each sub-edit. `multiedit` is not a magic blur — it is a transactional wrapper around the same write rules.

---

## Why This Matters Beyond Format Choices

The lesson generalizes beyond editing.

Every time you find yourself writing prompt instructions that say "be careful to escape X" or "make sure the JSON is valid" or "close all your tags properly," you are asking the model to do work that the architecture should do. The model is a reasoning engine, not a serialization library.

The facade that survived — six tools, one rule, no transport format — is smaller than the system it replaced. That is the point. The smaller API is not a simplification of the backend. The backend is more complex than ever. The smaller API is a simplification of the cognitive load on the model.

And in agent engineering, cognitive load on the model is the resource that matters most.

---

← [The Semantic Memory That Survived](39-the-semantic-memory-that-survived.md) | [The Book of Grinta](README.md) | [The Mode Split](41-the-mode-split.md) →
