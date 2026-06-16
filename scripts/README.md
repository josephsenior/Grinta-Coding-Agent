# Repository scripts (`scripts/`)

Small utilities for bootstrapping, release smoke checks, evals, and ad-hoc
diagnostics. Run commands from the **repository root** unless noted otherwise.

For CI gates and layer-boundary checks, see [`backend/scripts/`](../backend/scripts/README.md).

## Environment bootstrap

| Script | Purpose |
| --- | --- |
| [`bootstrap_env.py`](bootstrap_env.py) | Canonical `uv sync` wrapper for dependency profiles (`base`, `browser`, `dev`, `dev-test`, `dev-test-browser`). Used by CI, `START_HERE`, and `CONTRIBUTING.md`. |
| [`check_contributor_bootstrap.sh`](check_contributor_bootstrap.sh) | Quick sanity check that `bootstrap_env.py dev-test` succeeds on Linux/macOS. |

## Release / onboarding smoke

| Script | Purpose |
| --- | --- |
| [`smoke_install.sh`](smoke_install.sh) / [`.ps1`](smoke_install.ps1) | Install the built wheel into a clean venv and verify `grinta --help`, optional extras, and `grinta init` non-TTY guard. |
| [`smoke_source_onboarding.sh`](smoke_source_onboarding.sh) / [`.ps1`](smoke_source_onboarding.ps1) | Source-checkout smoke: sync `base` profile and run `grinta --help`. |
| [`Dockerfile.smoke`](Dockerfile.smoke) | Minimal image for wheel-install smoke in containerized CI. |

## Evals

| Script | Purpose |
| --- | --- |
| [`evals/run_realworld_task.py`](evals/run_realworld_task.py) | Run one task from the agent comparison pack headlessly with `settings.bench.json` overrides. |
| [`score_agent_eval_pack.py`](score_agent_eval_pack.py) | Score or template-fill results from [`evals/agent_comparison_pack.json`](evals/agent_comparison_pack.json). |
| [`evals/agent_comparison_pack.json`](evals/agent_comparison_pack.json) | Vendor-neutral eval task definitions. |
| [`evals/grinta_results.template.json`](evals/grinta_results.template.json) | Blank results template for manual scoring. |

## Maintainer / diagnostics

| Script | Purpose |
| --- | --- |
| [`discover_public_imports.py`](discover_public_imports.py) | AST-only import manifest for refactor planning; output defaults to `docs/internals/import-manifest.json`. |
| [`strip_session_log.py`](strip_session_log.py) | Strip noisy session log lines and write an audit summary via `backend.core.session_log_audit`. |
| [`test_provider_connection.py`](test_provider_connection.py) | Manual cloud-provider ping (`vercel`, `nvidia`). Replaces the old per-provider test scripts. |
| [`probe_llm_settings.py`](probe_llm_settings.py) | Manual ping using your configured `settings.json` profile (model, provider, API key). |

## Manual tests (not in this folder)

End-to-end verification scripts that are not collected by pytest live under
[`backend/tests/manual/`](../backend/tests/manual/README.md), including
[`chess_e2e_verify.py`](../backend/tests/manual/chess_e2e_verify.py) for the
content-escape / FileEditor pipeline.
