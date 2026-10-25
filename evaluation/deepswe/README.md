# Grinta × DeepSWE v1.1

This is the preliminary, reproducible Grinta evaluation protocol. It uses the
official DataCurve **Pier** harness and DeepSWE's external behavioral verifier.
Grinta's own `FINISHED` state is diagnostic and can never produce a PASS.

## Agentless-ML shared comparison (model-free)

The separate shared comparison path accepts an exported DeepSWE `task.json`
and its adjacent native public report. It does not inherit the older protocol's
model defaults or launch a model:

```bash
python -m evaluation.deepswe.run_grinta \
  --workspace /path/to/clean-pinned-checkout \
  --shared-task /path/to/task.json \
  --task-id actionlint-action-pinning-lint \
  --grinta-commit <current-commit> \
  --output-dir /path/to/output --dry-run
```

This mode verifies hashes, the starting commit/tree and a clean checkout, then
reports the shared problem, public resources and configured environment. It
bypasses legacy model settings. Shared-record execution without `--dry-run`
is blocked until model/access, budgets and observed environment matching are
implemented. Ordinary Grinta and the older Pier path are unchanged.

`shared_task.py` is the byte-identical stdlib reader mirrored from Agentless-ML's
`src/agentless_ml/shared_task.py`; update both copies together. Agentless-ML's
`tools/compare_shared_deepswe_starts.py` exercises both actual CLI preflights.
Actionlint and Numba matched in the 25 October 2026 source/configuration checks.
These checks did not install Grinta inside a task container, prove Pier runtime
equivalence, enforce the remaining edit restrictions or run benchmark tests.
The later [controlled container rehearsal](https://github.com/josephsenior/Agentless-ML/blob/main/docs/history/shared-container-rehearsal-2026-10-25.md)
did compare real Agentless and Pier containers after installing Grinta core.
Their observed settings and starting source bytes/modes matched. Native edits
passed the authored unit test, and unsupported edits were rejected. This is
one diagnostic environment; model transport remains deferred.

The opt-in Pier parameter `preserve_task_toolchain=True` uses the image's
existing curl/Git/Node/npm/uv and installs Codex under the image user's private
directory. It avoids package-manager upgrades, Node replacement and system
symlinks. Missing prerequisites stop setup for review. The legacy installer
remains the default for historical evaluations.

`security.comparison_edit_profile: "agentless-ml-v1"` enables completed-action
source checks in the real RuntimeExecutor and a final patch check. Text edits,
creation, deletion and renaming are permitted; changed binary/non-UTF-8 files,
mode changes, symlink/submodule changes and unsupported paths stop the attempt.
Ignored build products remain outside the submitted source inventory. Run build
products outside source or use the repository's existing ignore rules.
The guard checks resulting states, as agreed: deleting and restoring a file
within one command is allowed. It does not monitor intermediate writes inside
that command or claim protection against a deliberately hostile process.

`shared_environment.create_shared_environment()` applies the shared record's
container limits through Pier's real Docker lifecycle. Runtime installation is
completed beforehand into an explicitly identified prepared image, which both
arms can use. The profile disables agent egress, drops capabilities, uses a
read-only root and confines writes to `/tmp`, including Pier's internal logs.
It passes source archives without Windows newline rewriting. Cleanup removes
only the session's containers and volumes and preserves the shared images.

`python -m evaluation.deepswe.rehearse_shared_runtime` runs a bounded provisioning
diagnostic with task-tool fingerprints before and after installation. Network
is enabled during this setup phase. `--source-archive` accepts a local Git
archive of the exact requested commit to avoid unreliable Git transfer;
archive files, executable bits and symlink targets are checked against Git.
The diagnostic does not copy authentication or call a model.

## Paired case study

The completed eight-task paired case study is documented in
[`CASE_STUDY_2026-09-01.md`](CASE_STUDY_2026-09-01.md). It is a carefully
audited, task-by-task comparison of Grinta and native Codex CLI under the same
Luna-medium subscription-auth configuration. It is deliberately separate from
the frozen 20-task protocol below: it has one rollout per arm, selected tasks,
and two Grinta revisions, so it must not be presented as a DeepSWE leaderboard
score or a general model ranking.

## What is being evaluated

The agent under test is **Grinta**, not Pier's built-in Codex agent:

```text
Pier / DeepSWE task
        ↓
custom Grinta Pier adapter
        ↓
normal headless Grinta Orchestrator
        ↓
Codex app-server model transport (ChatGPT subscription)
        ↓
Grinta tools, state, validation, recovery, patch, and trajectory
        ↓
external DeepSWE verifier
```

`--agent-import-path evaluation.deepswe.pier_agent:Grinta` is what selects the
Grinta harness. Codex supplies the model responses inside Grinta; the command
never uses Pier's `-a codex` agent implementation.

## Frozen model policy

The reported 20-task subset uses:

- `codex/gpt-5.6-sol`
- reasoning effort `xhigh`
- ChatGPT subscription authentication
- no OpenAI API key and no usage-billed API fallback
- one attempt, concurrency 1, zero human intervention
- deterministic selection: `--n-tasks 20 --sample-seed 0`

`codex/gpt-5.6-luna` at `low` is reserved for a single unreported smoke trial.
It must not be mixed into the reported results. The exact machine-readable
definition is in [`protocol.json`](protocol.json), and the resolved task IDs are
frozen in [`subset_seed0_n20.json`](subset_seed0_n20.json).

Token-derived catalog cost is stored only as an **API-equivalent estimate**. It
is not an actual subscription charge and cannot terminate a run. A ChatGPT plan
limit is classified as an infrastructure/capacity failure, never silently
retried with another model.

## Zero-token preflight

The preflight makes no model request:

```powershell
python -m evaluation.deepswe.preflight
```

It requires all of the following before any smoke run:

1. `codex login status` reports an authenticated Codex session. If not, run
   `codex login` and choose ChatGPT sign-in.
2. `datacurve-pier` is installed (`uv tool install datacurve-pier`).
3. Docker is running and accessible.
4. The tracked protocol still enforces `codex/` subscription transport and
   disables usage-billed API execution.

Do not add `OPENAI_API_KEY` to this workflow.

## Authentication boundary

Pier runs agents inside isolated containers. Pass the Codex CLI auth cache via
`CODEX_AUTH_JSON_PATH`; the adapter uploads it to a temporary container path and
removes it after the agent exits. Never copy `auth.json` into this repository,
the jobs directory, a trajectory, or a published artifact. Treat it like a
password.

On Windows the usual host path is:

```powershell
$env:CODEX_AUTH_JSON_PATH = "$env:USERPROFILE\.codex\auth.json"
```

## One smoke trial

First clone and pin DeepSWE, then run an oracle trial to verify Docker and the
verifier without using a model:

```powershell
git clone -c core.autocrlf=false https://github.com/datacurve-ai/deep-swe.git
git -C deep-swe checkout 0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea
git -C deep-swe rev-parse HEAD
pier run -p deep-swe/tasks/abs-module-cache-flags -a oracle `
  -o evaluation/deepswe/jobs --job-name smoke-oracle -q -y
```

The `core.autocrlf=false` clone option is mandatory on Windows. DeepSWE's
verifier entrypoints are Linux shell scripts; CRLF checkout conversion makes
them fail before a reward file can be produced.

Pier 0.3.1 also writes its generated Linux egress-proxy entrypoint with CRLF on
Windows. The custom Grinta adapter installs a narrowly scoped host-side shim
that normalizes only that generated `start-squid.sh` file to LF before Docker
Compose starts it. The shim is inactive on non-Windows hosts.

After the oracle passes, commit and push the Grinta benchmark adapter. Substitute
that exact 40-character commit below. Then run one **unreported** Luna trial:

```powershell
pier run -p deep-swe/tasks/abs-module-cache-flags `
  --agent-import-path evaluation.deepswe.pier_agent:Grinta `
  --model codex/gpt-5.6-luna `
  --agent-kwarg grinta_commit=<exact-40-character-Grinta-commit> `
  --agent-kwarg reasoning_effort=low `
  --agent-kwarg codex_version=0.150.1 `
  --agent-env CODEX_AUTH_JSON_PATH="$env:CODEX_AUTH_JSON_PATH" `
  --agent-timeout-multiplier 2 `
  -o evaluation/deepswe/jobs --job-name smoke-grinta -q -y
```

The adapter installs the exact Grinta revision and Codex CLI version inside the
task image, invokes normal headless Grinta, and writes `manifest.json`,
`model.patch`, and `trajectory.json` under Pier's agent artifacts.

For an unreported smoke run only, `--agent-kwarg
prevalidate_startup_health=true` runs Grinta's production dependency check as a
separate command in the task container, then suppresses its duplicate execution
during Orchestrator construction. This is useful for diagnosing container-only
startup interactions. Never use it for a reported run; its default is `false`.

Linux parser assets are prefetched into the task image during agent installation
so reported runs remain network-isolated. A cached legacy image can be exercised
with `--agent-kwarg allow_tree_sitter_bootstrap=true` for an unreported smoke
run; this temporarily adds GitHub release hosts to Pier's proxy allowlist while
Grinta's frozen security policy continues to block agent-initiated network and
package-install commands. Never enable this compatibility flag in reported runs.

## Reported deterministic subset

Only after the oracle and one Luna smoke trial succeed:

```powershell
$subset = Get-Content evaluation/deepswe/subset_seed0_n20.json | ConvertFrom-Json
$taskArgs = foreach ($taskId in $subset.task_ids) { '--include-task-name'; $taskId }

pier run -p deep-swe/tasks `
  --agent-import-path evaluation.deepswe.pier_agent:Grinta `
  --model codex/gpt-5.6-sol `
  --agent-kwarg grinta_commit=<exact-40-character-Grinta-commit> `
  --agent-kwarg reasoning_effort=xhigh `
  --agent-kwarg codex_version=0.150.1 `
  --agent-env CODEX_AUTH_JSON_PATH="$env:CODEX_AUTH_JSON_PATH" `
  @taskArgs --n-tasks 20 --sample-seed 0 -n 1 -k 1 --max-retries 0 `
  --agent-timeout-multiplier 2 `
  -o evaluation/deepswe/jobs --job-name grinta-deepswe-v1-1-n20-seed0 -q -y
```

Before publication, record the exact DeepSWE and Pier revisions, the resulting
20 task IDs, Grinta commit, config/protocol hashes, verifier output, patches, and
trajectories. Label the result “DeepSWE v1.1 — deterministic preliminary subset
(n=20, seed=0),” not a full DeepSWE score.

## Direct runner dry-run

The lower-level runner validates provenance without model usage:

```powershell
python -m evaluation.deepswe.run_grinta `
  --workspace C:\path\to\prepared-task `
  --instruction "dry-run only" `
  --task-id example `
  --grinta-commit <exact-40-character-Grinta-commit> `
  --output-dir evaluation/deepswe/artifacts/example `
  --dry-run
```

External verifier output remains a separate immutable artifact. Do not copy its
verdict into Grinta's manifest.
