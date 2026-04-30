# 60-Second Demo Cast Script

This is the canonical recording script for the README demo cast. The goal:
in **60 seconds**, show a developer that Grinta installs cleanly, picks up a
local LLM automatically, and solves a real bug end-to-end.

> Record with [`asciinema`](https://asciinema.org/) (preferred for terminals)
> or any screen recorder of your choice. Output target: `docs/grinta-demo.gif`
> (referenced from `README.md`) and `docs/grinta-demo.cast`.

---

## Pre-flight (do this BEFORE pressing record)

1. Have **Ollama** running locally with `llama3.1:8b` (or any code-capable
   model) pulled. Grinta auto-detects it.
2. Use a fresh demo workspace:

   ```bash
   mkdir grinta-demo && cd grinta-demo
   git init -q
   ```

3. Drop a small broken Python file into the workspace:

   ```python
   # demo_app/calc.py
   def average(nums):
       return sum(nums) / len(nums)  # ZeroDivisionError on empty list
   ```

4. Drop a failing pytest:

   ```python
   # tests/test_calc.py
   from demo_app.calc import average

   def test_empty_list_returns_zero():
       assert average([]) == 0
   ```

5. Confirm `pytest -q` fails with `ZeroDivisionError`.
6. Set terminal size to **100x30**, font size to ~16pt.
7. Clear the terminal. Take a breath.

## Recording (the 60-second take)

```bash
# 0:00–0:08  — Install
asciinema rec docs/grinta-demo.cast
pipx install grinta-ai
clear

# 0:08–0:15  — Init: wizard auto-detects Ollama
grinta init
# (accept all defaults — Ollama is auto-detected)
clear

# 0:15–0:22  — Launch
grinta
# > "fix the failing test in tests/test_calc.py"

# 0:22–0:55  — Watch HUD: tokens / cost (0.00 USD on Ollama) / latency
#              tick up while Grinta:
#                 1. runs pytest, sees ZeroDivisionError
#                 2. opens calc.py via `read_symbol_definition`
#                 3. patches average() to handle empty list
#                 4. re-runs pytest, sees green
#                 5. announces FINISHED

# 0:55–1:00  — /cost  → "0 tokens billed, $0.00 — local model"
/exit
```

Stop the recording. Trim with `asciinema upload` or convert to GIF with
[`agg`](https://github.com/asciinema/agg):

```bash
agg --font-size 18 --theme monokai docs/grinta-demo.cast docs/grinta-demo.gif
```

## What viewers should walk away thinking

- "Wait, that ran fully offline."
- "It actually checked the test passed before saying done."
- "I can see exactly what it cost me."
- "I want to try this on my repo."

That's the whole launch pitch in 60 seconds.
