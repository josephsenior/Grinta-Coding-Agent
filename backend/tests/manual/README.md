# Manual verification scripts

This folder holds **manual** smoke and inspection scripts. They are **not**
collected by `pytest` (the folder is excluded via `norecursedirs` in
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
| `chess_e2e_verify.py` | End-to-end check that over-escaped HTML/CSS tool payloads are repaired and written via `FileEditor`. Not a TUI script; exercises `content_escape_repair` + execution. |
| `provider_connection_check.py` | Manual cloud-provider ping (`vercel`, `nvidia`). Requires the matching API key in the environment or `.env`. |
| `verify_rich_markup_crash.py` | Ad-hoc Rich markup probe for middle-dot / timing suffix edge cases. |
| `cli_entry_smoke.py` | Launches the real CLI via subprocess and checks `/help` output. Requires API key env vars. |

## How to run

From the repository root:

```powershell
uv run python backend/tests/manual/inspect_tui.py
uv run python backend/tests/manual/smoke_test_tui.py
uv run python backend/tests/manual/tui_diff_smoke.py
uv run python backend/tests/manual/tui_dot_smoke.py
uv run python backend/tests/manual/chess_e2e_verify.py
uv run python backend/tests/manual/provider_connection_check.py vercel
uv run python backend/tests/manual/verify_rich_markup_crash.py
uv run python backend/tests/manual/cli_entry_smoke.py
```

Each script is self-contained and runs headlessly. If a script needs UTF-8
stdout on Windows it reconfigures it itself.

## Why this folder exists (and is not under `tests/unit`)

These scripts exercise the real Textual rendering path, which is intentionally
left out of the automated suite: it depends on terminal capabilities, is slow,
and its failure modes are visual rather than assertable. They live here so
they are findable and reviewable, without being silently executed every time
someone runs `pytest`.
