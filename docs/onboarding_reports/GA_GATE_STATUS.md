# GA onboarding gate status

Last updated: 2026-06-25

This file tracks **honest** progress toward the fresh-machine onboarding gate in
[FRESH_MACHINE_ONBOARDING.md](../FRESH_MACHINE_ONBOARDING.md). CI smoke tests
do **not** satisfy the interactive GA requirement.

## Required evidence (minimum 6 reports)

| Path | OS | Interactive reports needed | Interactive reports filed | CI-only substitutes |
| --- | --- | --- | --- | --- |
| pipx | Linux | 3 | 0 | 1 (`pipx_linux_1`) |
| pipx | Windows | 3 | 1 (`pipx_windows_1`, partial) | 0 |
| source uv | Linux | 3 | 0 | 2 (`source_linux_1`, `source_linux_2`) |
| source uv | Windows | 3 | 1 (`source_windows_1`) | 1 (`source_windows_2`, non-TTY only) |

## Gate verdict

**Not ready for GA onboarding sign-off.**

What is proven today:

- Wheel and source **install** smoke on Linux and Windows (CI)
- Non-TTY `grinta init` guard (exit 3)
- One partial Windows interactive path (developer machine with prior context)

What is **not** proven:

- Interactive `grinta init` wizard on a never-used Linux VM (pipx ×3)
- Interactive source checkout on a never-used Linux VM (×3)
- macOS pipx or source path
- First real agent task after TUI launch on fresh Linux machines

## Next actions before `v1.0.0` tag

1. Run pipx Linux interactive report #1 on a fresh VM; file under this folder.
2. Repeat for pipx Linux #2 and #3 (or document variance across distros).
3. Run source Linux interactive on a fresh VM (×3 or refresh policy per RELEASE_CHECKLIST).
4. Update [README.md](README.md) tracking matrix — mark rows `interactive-pass` vs `ci-only`.
5. Sign off in [RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md) only when the matrix is green.

## Report quality bar

Each filed report must state:

- **Evidence type:** `interactive-fresh-machine` or `ci-smoke-only`
- Whether `~/.grinta` was absent before install
- Whether `grinta init` ran in a real TTY (not piped / not CI stub)
- Pass/fail for install, init, TUI launch, first `/health` task

CI-only reports may be kept for regression tracking but **must not** count toward GA.
