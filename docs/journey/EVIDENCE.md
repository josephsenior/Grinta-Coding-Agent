# Journey Evidence Index

This index separates three kinds of material used in the journey.

- **Direct evidence:** the current repository contains the implementation,
  tests, trace, or report at a stable path.
- **Git evidence:** the event is recoverable from repository history, but the
  current tree no longer contains the complete subsystem.
- **Memoir:** a dated first-person account without a complete reproducible
  artifact in this checkout. Memoir can be useful, but it is not a benchmark.

The classification is intentionally conservative. “Finished,” “tests passed,”
and “met the original specification” are treated as separate claims.

## Direct Evidence

| Claim | Evidence | Boundary |
| --- | --- | --- |
| A public autonomous run lasted about 106 minutes | [`traces/ouroboros/README.md`](../../traces/ouroboros/README.md), [`session.audit.txt`](../../traces/ouroboros/session.audit.txt); introduced in commit `4ad1b0d62` | The generated system contains deliberate simplifications. The raw archive is kept outside Git and should be attached to a release/evidence record before it is cited as a downloadable artifact. |
| A separate July 9 run reached `FINISHED` after 273.5 minutes | [`docs/evidence/2026-07-09-autonomous-run-report.md`](../evidence/2026-07-09-autonomous-run-report.md) | This is a sanitized report. It records 16,393 events and 373 tool outcomes, but does not publish the complete raw trace. |
| Durable task state became a subsystem rather than a compaction side effect | `backend/task_state/`, tests under `backend/tests/unit/task_state/`; commits `83a5ab697`, `b26bbddfc`, `9155ea9b9` | The implementation continued changing after the initial subsystem landed. |
| Acceptance criteria became explicit data before task state was separated | `backend/execution/acceptance_criteria.py`; commits `03eff6eb2`, `61db0bd80`, `64f89d83e`, `aa521e25b` | This was an intermediate layer, not the final continuity model. |
| Project memory became orchestrator-owned | `backend/context/memory/project_memory.py`; commit `e35189783` | This is repository memory, not a claim that the system learns autonomously without review. |
| Prompt caching became capability-driven | `backend/inference/caching/prompt_caching.py`; commits `b8646a640`, `6229b5332` | Provider support still depends on the selected model and client capabilities. |
| The current public file API has six tools | `backend/engine/tools/native_file_tools.py`; removal commit `1365596a3`; [CHANGELOG.md](../../CHANGELOG.md) | Older chapters describe earlier APIs and keep their historical names. |
| PowerShell became the native-Windows onboarding default | `settings.template.json`, `backend/cli/onboarding/settings_defaults.py`; commit `1af161bb6` | Git Bash remains supported and WSL is a separate environment. |
| First-run and cross-platform onboarding became a gated reliability concern | `backend/cli/onboarding/`, onboarding reports, and setup scripts; commits `566591f70`, `baaf5f1ea`, `1bb3adf4d`, `0d6149417` | Passing an onboarding gate does not certify every third-party shell or environment. |
| `sandboxed_local` exists as process-scoped isolation | `backend/execution/sandboxing.py`, `backend/execution/sandbox_helpers/`, tests, and [SUPPORT_MATRIX.md](../SUPPORT_MATRIX.md) | Interactive PTY sessions are not covered; platform tools such as `bwrap` may be required. It is not VM isolation. |
| The package remains a release candidate despite internal 8.1 → 9.0 phase labels | `pyproject.toml` (`1.0.0rc1`), [RELEASE_NOTES_v1.0.0-rc1.md](../RELEASE_NOTES_v1.0.0-rc1.md) | Internal refactor-plan numbers are not semantic versions. |
| CI coverage and cross-platform gates expanded in July | workflow files, [CI.md](../CI.md), commits `60ee4bb36`, `35bcfdee2`, `58837abe3`, `785760631` | A threshold and a passing run are different facts. Consult the current CI run for live status. |

## Git Evidence and Archaeology

The SaaS backend, container runtime, multi-agent planning system, prompt
optimization experiments, and earlier UI layers were removed or substantially
reshaped. Their chapters cite historical line counts as snapshots. Those counts
should be backed by a tagged tree plus a repeatable counting command before they
are reused in a resume, benchmark, or product comparison.

Recommended receipt format:

```text
claim: 20,458 lines in MetaSOP
tree: <tag or commit>
paths: <included paths>
command: <exact counting command>
generated files excluded: yes/no
tests or run artifact: <path or URL>
```

Until that manifest exists, the exact historical counts in chapters 00–07 are
best read as repository archaeology reported by the author, not independently
reproduced measurements.

## Memoir-Only Claims

The March Raft/RFT runs in
[The Empty Folder Trials](44-the-empty-folder-trials.md) do not currently have a
self-contained public archive in this checkout. The chapter now states that
boundary and no longer describes the runs as intervention-free.

The internal cross-agent evaluation runs described in
[The Vendor-Neutral Bench](38-the-vendor-neutral-bench.md) are not published.
The scorer and pack can be inspected, but unpublished scores cannot substantiate
public superiority claims.

## How to Add a Receipt

For a new journey claim, record:

1. date, commit, model/provider, and relevant settings
2. exact prompt or a clearly labeled sanitized prompt
3. duration, cost, token accounting method, and human interventions
4. generated artifact or diff
5. exact validation command and raw result
6. known gaps between the validation and the original specification

If privacy prevents publication, say what was omitted and narrow the claim to
what the published evidence can support.

---

← [The Book of Grinta](README.md)
