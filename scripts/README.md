# Repository scripts (`scripts/`)

Small utilities for bootstrapping, release smoke checks, evals, and ad-hoc
diagnostics. Run commands from the **repository root** unless noted otherwise.

For CI gates and layer-boundary checks, see [`backend/scripts/`](../backend/scripts/README.md).

## Environment bootstrap

| Script | Purpose |
| --- | --- |
| [`bootstrap_env.py`](bootstrap_env.py) | Canonical `uv sync` wrapper for dependency profiles (`base`, `browser`, `dev`, `dev-test`, `dev-test-browser`). Used by CI, `START_HERE`, and `CONTRIBUTING.md`. |
| [`check_contributor_bootstrap.sh`](check_contributor_bootstrap.sh) | Quick sanity check that `bootstrap_env.py dev-test` succeeds on Linux/macOS. |

## Launch / Docker

| Script | Purpose |
| --- | --- |
| [`launch/start_here.ps1`](launch/start_here.ps1) / [`launch/start_here.sh`](launch/start_here.sh) | Source-checkout bootstrap: sync deps, init wizard, doctor (does not launch TUI). |
| [`launch/start_here_pipx.ps1`](launch/start_here_pipx.ps1) / [`launch/start_here_pipx.sh`](launch/start_here_pipx.sh) | pipx-installed `grinta` flow (no `uv`/bootstrap). |
| Root [`START_HERE.ps1`](../START_HERE.ps1) / [`start_here.sh`](../start_here.sh) | Unified entry: auto-picks source vs pipx (`-Pipx` / `--pipx` to override). |
| [`docker/docker_start.ps1`](docker/docker_start.ps1) / [`docker/docker_start.sh`](docker/docker_start.sh) | Optional Docker helper; exits with guidance when no `docker-compose.yml` / `compose.yml` exists in the repo (experimental GHCR image path is documented in [QUICK_START.md](../docs/QUICK_START.md)). |
| [`build.sh`](build.sh) | `uv build -v` wrapper. |

## Release / onboarding smoke

| Script | Purpose |
| --- | --- |
| [`smoke/smoke_install.sh`](smoke/smoke_install.sh) / [`.ps1`](smoke/smoke_install.ps1) | Install the built wheel into a clean venv and verify `grinta --help`, optional extras, and `grinta init` non-TTY guard. |
| [`smoke/smoke_source_onboarding.sh`](smoke/smoke_source_onboarding.sh) / [`.ps1`](smoke/smoke_source_onboarding.ps1) | Source-checkout smoke: sync `base` profile and run `grinta --help`. |
| [`smoke/Dockerfile.smoke`](smoke/Dockerfile.smoke) | Minimal image for wheel-install smoke in containerized CI. |

## Evals

| Script | Purpose |
| --- | --- |
| [`evals/run_realworld_task.py`](evals/run_realworld_task.py) | Run one task from the agent comparison pack headlessly with `settings.bench.json` overrides. |
| [`evals/score_agent_eval_pack.py`](evals/score_agent_eval_pack.py) | Score or template-fill results from [`evals/agent_comparison_pack.json`](evals/agent_comparison_pack.json). |
| [`evals/agent_comparison_pack.json`](evals/agent_comparison_pack.json) | Vendor-neutral eval task definitions. |
| [`evals/grinta_results.template.json`](evals/grinta_results.template.json) | Blank results template for manual scoring. |

## Maintainer / diagnostics

| Script | Purpose |
| --- | --- |
| [`discover_public_imports.py`](discover_public_imports.py) | AST-only import manifest for refactor planning; output defaults to `docs/internals/import-manifest.json`. |
| [`strip_session_log.py`](strip_session_log.py) | Strip noisy session log lines and write an audit summary via `backend.core.session_log_audit`. |
| [`provider_connection_check.py`](../backend/tests/manual/provider_connection_check.py) | Manual cloud-provider ping (`vercel`, `nvidia`). Lives under `backend/tests/manual/`. |
| [`probe_llm_settings.py`](probe_llm_settings.py) | Manual ping using your configured `settings.json` profile (model, provider, API key). |

## Manual tests (not in this folder)

End-to-end verification scripts that are not collected by pytest live under
[`backend/tests/manual/`](../backend/tests/manual/README.md), including
[`chess_e2e_verify.py`](../backend/tests/manual/chess_e2e_verify.py) for the
content-escape / FileEditor pipeline.
