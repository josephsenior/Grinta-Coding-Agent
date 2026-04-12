# The Identity and Execution Crisis

As Grinta evolved, building more capability into the agent inevitably surfaced new classes of friction. The more tools and autonomy we added, the more ways the system found to trip over its own shoelaces. A major bug-hunting and refactoring session highlighted four distinct crises in how the agent operated, understood its environment, and reported failures.

## 1. Analysis Paralysis and Prompt Bloat

The first symptom was the agent getting stuck in an endless loop of exploration. It would list directories, read files, and analyze the codebase without actually performing the requested fix.

**The Problem:** Over time, the system prompts (`<TASK_ROUTING>`, `<AUTONOMY>`, etc.) had accumulated conflicting instructions. Safeguards meant to prevent reckless edits were accidentally telling the agent to "look but don't touch" unless it was absolutely certain, leading to an over-cautious exploration loop.

**The Solution:** We simplified the prompt partials (like `system_partial_00_routing.md`), stripping out the bloat. We introduced explicit fail-fast debug routing instructions:
> "Run one concrete reproducer command first... Inspect only files implicated by that failure... Apply the smallest safe fix."

This re-aligned the agent to prioritize execution and verification over endless static code analysis.

## 2. Silent Startup Crashes (The Void of `sys.excepthook`)

Shortly after the prompt adjustments, the Grinta CLI began mysteriously crashing entirely. Booting the app simply yielded Exit Code 1 with a generic "Initialization failed" message, returning instantly to the terminal with zero logs.

**The Problem:** To provide a beautiful, seamless UI using `rich.Live`, the CLI intentionally suppressed standard Python exception tracing (`sys.excepthook`). However, an earlier automated file-edit attempt had corrupted two critical backend files (`backend/execution/utils/file_editor.py` and `backend/engine/tools/search_code.py`) with malformed syntax. Because standard out was muted, these fatal `SyntaxError`s during the import phase were swallowed whole.

**The Solution:** We bypassed the CLI launcher and ran bare python (`python -c "import backend.engine.orchestrator"`) to expose the traceback. Having identified the corrupted files, we executed `git checkout` to restore their unbroken states. We then injected `LOG_TO_FILE=true` and `DEBUG_LLM=true` into the `.env` to ensure future diagnosis wouldn't require blind guesswork.

## 3. The PowerShell Identity Crisis

While attempting to test code in a Windows environment, the agent kept failing simple shell tasks. It would try to run commands like `cd forntend && pnpm lint | head -100` or `timeout 10s npm run dev 2>&1 || true`. These commands crashed instantly.

**The Problem:** There was a profound mismatch between the prompt builder and the executor.
1. The `prompt_builder.py` checked for Bash availability. If it didn't find Git Bash, it simply omitted the `<SHELL_IDENTITY>` block altogether, leaving the LLM to assume a generic (often Unix-leaning) shell.
2. Meanwhile, the actual terminal tool executor (`backend.engine.tools.prompt`) had complex logic forcing PowerShell behavior on Windows.

The agent was metaphorically speaking French while locked in a room that only understood German.

**The Solution:** 
1. We synced the prompt's environment logic directly with the executor's resolution check (`uses_powershell_terminal()`).
2. We added an explicit `<SHELL_IDENTITY>` instruction for PowerShell:
   > "Your terminal is **PowerShell** running on Windows. Use **PowerShell syntax exclusively**... FORBIDDEN: `&&`, `||`, `find`, `cat`, `grep`, `head`..."

By explicitly banning Unix-isms on Windows, the agent was immediately grounded in the correct syntax context.

## 4. The Fragile Patch Fallback

When the agent correctly identified a bug, it often tried to use `str_replace_editor`. But if the LLM's whitespace/indentation estimation didn't perfectly match the file, the tool would fail. When that happened, the LLM had a fallback strategy: `apply_patch`, allowing it to supply a Unified Diff.

However, the fallback failed with:
`SyntaxError: invalid syntax`

**The Problem:** The `apply_patch` tool was constructed by sending a base64-encoded Python script to the terminal:
`python -c "import base64...; patch=...; dry_run=...; if ...:"`
The script was jammed onto a single line separated by semicolons. Python immediately throws parser errors if you attempt to declare statements on the same line *after* beginning an `if` block.

**The Solution:** We rewrote the generator in `apply_patch.py` to compile a clean, natively formatted, multi-line Python script before applying base64 encoding. Furthermore, we updated the `<EDITOR_GUIDE>` prompt to explicitly recommend `apply_patch` as the primary choice for complex whitespace changes or multi-file diff edits.

## Conclusion

Together, these fixes fundamentally shifted Grinta from a cautious, occasionally confused observer into a unified, stable system that fully understands its physical execution environment (PowerShell vs Bash), handles edge-case editing requests natively, and speaks clearly when its foundational systems break.
