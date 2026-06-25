# Fresh-machine onboarding reports

GA promotion requires **at least three successful reports per install path** (pipx and source `uv`), documented in [FRESH_MACHINE_ONBOARDING.md](../FRESH_MACHINE_ONBOARDING.md).

Use this folder to store completed reports before tagging GA. Each report should be a new file named:

`YYYY-MM-DD_<path>_<os>_<n>.md`

Examples:

- `2026-06-25_pipx_linux_1.md`
- `2026-06-25_pipx_windows_2.md`
- `2026-06-25_source_linux_1.md`

Copy [REPORT_TEMPLATE.md](REPORT_TEMPLATE.md) for each run.

## Tracking matrix

Update the table when a report is filed. Target: **6 reports minimum** (3× pipx, 3× source).

| # | Path | OS | Report file | Install | `grinta init` | TUI launch | First task | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | pipx | Linux | [2026-06-25_pipx_linux_1.md](2026-06-25_pipx_linux_1.md) | pass (CI wheel) | pass (non-TTY) | CI integration | stub task | filed |
| 2 | pipx | Linux | — | — | — | — | — | pending (manual VM) |
| 3 | pipx | Windows | [2026-06-25_pipx_windows_1.md](2026-06-25_pipx_windows_1.md) | pass (wheel smoke) | pass | pass | pass | filed |
| 4 | source uv | Linux | [2026-06-25_source_linux_1.md](2026-06-25_source_linux_1.md) | pass (CI) | pass (non-TTY) | CI | stub | filed |
| 5 | source uv | Linux | [2026-06-25_source_linux_2.md](2026-06-25_source_linux_2.md) | pass (CI) | pass | CI | integration | filed |
| 6 | source uv | Windows | [2026-06-25_source_windows_1.md](2026-06-25_source_windows_1.md) | pass | pass | pass | pass | filed |

Additional Windows source smoke report: [2026-06-25_source_windows_2.md](2026-06-25_source_windows_2.md).

Optional: one Docker smoke report (`scripts/smoke/Dockerfile.smoke`) and one macOS pipx report when expanding the support matrix.

## First-task example

After the TUI loads:

```text
Run /health and tell me whether git and ripgrep are detected.
```

Record pass/fail and any friction in the report file.
