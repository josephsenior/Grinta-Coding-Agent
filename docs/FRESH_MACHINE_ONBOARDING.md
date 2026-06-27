# Fresh-machine onboarding checklist

Use this checklist before GA promotion, when refreshing onboarding evidence, and whenever onboarding-affecting changes land.
It implements the **CLI onboarding confidence** gate in
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).

## GA gate status

Honest progress tracking lives in
[onboarding_reports/GA_GATE_STATUS.md](onboarding_reports/GA_GATE_STATUS.md).
CI smoke passes **do not** satisfy the interactive GA requirement.

## What CI automates

The [**Smoke Install** workflow](../.github/workflows/smoke-install.yml) runs on
every PR and on `main` for **Linux** and **Windows**:

| Check | Wheel install (`scripts/smoke_install.*`) | Source checkout (`scripts/smoke_source_onboarding.*`) |
| --- | --- | --- |
| Clean venv / dependency sync | Yes | Yes (`bootstrap_env.py base`) |
| `import backend` + `grinta --help` | Yes | Yes |
| Optional-imports verifier | Yes (from repo checkout) | No |
| `grinta init` rejects non-TTY (exit 3) | Yes | Yes |
| `grinta init --non-interactive` (env-based write) | Yes | Yes |
| Interactive `grinta init` | No | No |
| First real agent task | No | No |

CI builds a **local wheel** (`uv build --wheel`) and installs it into a throwaway
venv — it does not hit PyPI unless you run the scripts without `WHEEL_DIR` set.

Local equivalents:

```bash
uv build --wheel
WHEEL_DIR=./dist ./scripts/smoke_install.sh
./scripts/smoke_source_onboarding.sh
```

```powershell
uv build --wheel
$env:WHEEL_DIR = '.\dist'
.\scripts\smoke_install.ps1
.\scripts\smoke_source_onboarding.ps1
```

## What you must run manually (GA evidence and refresh)

Before **1.0.0 GA**, and again after onboarding-affecting changes, keep **at least three successful reports** current for each required path below. If the current release line already has passing reports, refresh that evidence rather than starting the process definition from zero. Use a machine or VM that has **never** run Grinta before for each new report (no `~/.grinta`, no prior `settings.json` in the target directory).

### A. `pipx` install (required ×3)

See [QUICK_START.md](QUICK_START.md#consumer-mode-use-the-app). Prerequisites: Python 3.12+ and `pipx`.

```bash
pipx install grinta-ai
grinta
```

Record whether setup completed during first `grinta` launch or via optional `grinta init`.

First task example (after the TUI loads):

```text
Run /health and tell me whether git and ripgrep are detected.
```

Record:

- OS and version (Linux or Windows)
- Python version
- Provider chosen during setup (first `grinta` or `grinta init`)
- Pass / fail for: install, init, TUI launch, first task
- Notes (errors, friction, screenshots)

File each report under [onboarding_reports/](onboarding_reports/) using [REPORT_TEMPLATE.md](onboarding_reports/REPORT_TEMPLATE.md) and update the tracking matrix in [onboarding_reports/README.md](onboarding_reports/README.md).

### B. Source `uv` checkout (required ×3)

See [QUICK_START.md](QUICK_START.md#dev-mode-source-checkout). Prerequisites: none — start scripts install `uv` and Python 3.12 when missing.

```bash
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git
cd Grinta-Coding-Agent
bash start_here.sh    # Windows: .\START_HERE.ps1
```

First task example (after the TUI loads):

```text
Run /health and tell me whether git and ripgrep are detected.
```

Same fields as section A.

### C. Docker (optional ×1)

Experimental path — one successful report is enough for signal, not a merge blocker.

```bash
docker pull ghcr.io/josephsenior/grinta:latest
docker run -it --rm -v "$PWD:/work" -w /work \
  -e LLM_API_KEY=${LLM_API_KEY} \
  ghcr.io/josephsenior/grinta:latest
```

## Report template

Copy into a release issue, RC feedback issue, or internal GA doc:

| # | Path | OS | Python | Install OK | `init` OK | TUI / CLI OK | First task OK | Tester | Date | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | pipx | | | | | | | | | |
| 2 | pipx | | | | | | | | | |
| 3 | pipx | | | | | | | | | |
| 4 | source uv | | | | | | | | | |
| 5 | source uv | | | | | | | | | |
| 6 | source uv | | | | | | | | | |
| 7 | docker (opt.) | | | | | | | | | |

**GA criteria:** the current evidence set has rows 1–6 passing with no P0 friction; row 7 optional. Refresh the table whenever onboarding-relevant behavior changes.

## When something fails

1. Note the exact command, exit code, and stderr.
2. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
3. Open an issue with the [RC Feedback template](../.github/ISSUE_TEMPLATE/rc_feedback.yml)
   or a bug report if it is a defect.

## Related docs

- [INSTALL.md](INSTALL.md) — install paths
- [QUICK_START.md](QUICK_START.md) — minimal consumer and dev commands
- [USER_GUIDE.md](USER_GUIDE.md) — configuration and first run
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) — full GA gates
- [CI.md](CI.md) — how Smoke Install fits in CI
