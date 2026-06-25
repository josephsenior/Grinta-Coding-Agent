# Fresh-machine onboarding reports

GA promotion requires **at least three successful reports per install path** (pipx and source `uv`), documented in [FRESH_MACHINE_ONBOARDING.md](../FRESH_MACHINE_ONBOARDING.md).

Use this folder to store completed reports before tagging GA. Each report should be a new file named:

`YYYY-MM-DD_<path>_<os>_<n>.md`

Examples:

- `2026-06-25_pipx_linux_1.md`
- `2026-06-25_pipx_windows_2.md`
- `2026-06-25_source_linux_1.md`

Copy [REPORT_TEMPLATE.md](REPORT_TEMPLATE.md) for each run.

## GA gate status

See [GA_GATE_STATUS.md](GA_GATE_STATUS.md) for the honest interactive vs CI-only count.
**GA onboarding is not signed off** until three interactive fresh-machine reports
exist per required path (pipx + source uv).

## Tracking matrix

Update the table when a report is filed. Target: **6 interactive reports minimum**
(3× pipx, 3× source). Rows marked `ci-only` do **not** count toward GA.

| # | Path | OS | Report file | Evidence | Install | `grinta init` | TUI launch | First task | GA credit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | pipx | Linux | [2026-06-25_pipx_linux_1.md](2026-06-25_pipx_linux_1.md) | ci-only | pass (CI wheel) | pass (non-TTY) | CI integration | stub task | no |
| 2 | pipx | Linux | — | — | — | — | — | — | pending |
| 3 | pipx | Windows | [2026-06-25_pipx_windows_1.md](2026-06-25_pipx_windows_1.md) | partial | pass (wheel smoke) | pass | pass | pass | partial |
| 4 | source uv | Linux | [2026-06-25_source_linux_1.md](2026-06-25_source_linux_1.md) | ci-only | pass (CI) | pass (non-TTY) | CI | stub | no |
| 5 | source uv | Linux | [2026-06-25_source_linux_2.md](2026-06-25_source_linux_2.md) | ci-only | pass (CI) | pass | CI | integration | no |
| 6 | source uv | Windows | [2026-06-25_source_windows_1.md](2026-06-25_source_windows_1.md) | interactive | pass | pass | pass | pass | yes |
| 7 | source uv | Windows | [2026-06-25_source_windows_2.md](2026-06-25_source_windows_2.md) | ci-only | pass | pass (non-TTY guard) | n/a | n/a | no |

**Interactive credits toward GA today:** 1 partial (pipx Windows) + 1 (source Windows) — need 4+ more full interactive runs.

Optional: one Docker smoke report (`scripts/smoke/Dockerfile.smoke`) and one macOS pipx report when expanding the support matrix.

## First-task example

After the TUI loads:

```text
Run /health and tell me whether git and ripgrep are detected.
```

Record pass/fail and any friction in the report file.
