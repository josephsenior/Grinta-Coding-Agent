# GitHub Actions workflows

## Required on pull requests

| Workflow | Purpose |
| --- | --- |
| `py-tests.yml` | Sharded Linux unit coverage (75%), extended integration/e2e/stress, Windows/macOS gates |
| `lint.yml` | pre-commit, mypy, version/workflow consistency, repo hygiene |
| `bandit.yml` | Python SAST |
| `codeql.yml` | CodeQL static analysis |
| `dependency-review.yml` | Blocks high-severity dependency diffs on PRs |
| `pip-audit.yml` | Audits locked runtime dependencies for known CVEs |
| `smoke-install.yml` | Clean wheel + source onboarding smoke |
| `e2e-tests.yml` | CLI regression smoke when relevant paths change |

## Manual / advisory

| Workflow | Status | Notes |
| --- | --- | --- |
| `ghcr-build.yml` | **Disabled by default** | Legacy container build assets were removed from the repo. Kept for maintainers who may reintroduce `containers/` and runtime build scripts. |
| `vscode-extension-build.yml` | **Disabled by default** | VS Code extension assets were removed. Manual `workflow_dispatch` only. |
| `pypi-release.yml` | Manual | Trusted publishing to PyPI after pre-release checks. |
| `run-eval.yml` | Manual / label | Remote agent evaluation for behavior-sensitive changes. |
| `integration-runner.yml` | Conditional | Skips when eval assets are absent. |
| `lint-fix.yml` | Label `lint-fix` | Auto-fix pre-commit on demand. |

## Product note

Grinta ships as a **local CLI**. These workflows validate packaging, tests, and security — not a hosted multi-tenant deployment stack.
