# Manual TUI smoke scripts

This folder holds **manual** Textual UI smoke / inspection scripts. They are
**not** collected by `pytest` (the folder is excluded via `norecursedirs` in
`pytest.ini`, and no file name starts with `test_`).

Run them by hand when you are working on TUI rendering changes and want a
quick visual / textual sanity check that a widget still renders the way you
expect.

## Scripts

| File | What it does |
| --- | --- |
| `inspect_tui.py` | Mounts three `ActivityCard` variants (file create / read / edit) and dumps their rendered text. Use after changes to `ActivityCard` or `ActivityRenderer`. |
| `smoke_test_tui.py` | Mounts both `file_create` and `file_read` cards and prints their structured fields plus rendered text. Complements `inspect_tui.py`. |
| `tui_diff_smoke.py` | Renders an `ActivityCard` containing an encoded unified-diff payload. Use after touching `_encode_unified_diff_text` or diff rendering. |
| `tui_dot_smoke.py` | Tiny `Static` widget probe for the `\x1fgrinta-diff-ctx\x1f` sentinel handling. Writes a rendering trace to `test_output.txt` (gitignored). |

## How to run

From the repository root:

```powershell
uv run python backend/tests/manual/inspect_tui.py
uv run python backend/tests/manual/smoke_test_tui.py
uv run python backend/tests/manual/tui_diff_smoke.py
uv run python backend/tests/manual/tui_dot_smoke.py
```

Each script is self-contained and runs headlessly. If a script needs UTF-8
stdout on Windows it reconfigures it itself.

## Why this folder exists (and is not under `tests/unit`)

These scripts exercise the real Textual rendering path, which is intentionally
left out of the automated suite: it depends on terminal capabilities, is slow,
and its failure modes are visual rather than assertable. They live here so
they are findable and reviewable, without being silently executed every time
someone runs `pytest`.
