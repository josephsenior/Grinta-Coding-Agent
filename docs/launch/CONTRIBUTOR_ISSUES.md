# Contributor Issue Drafts

These issues are ready to publish when the GitHub integration has issue-write permission. The titles, labels, scope, and acceptance criteria are intentionally concrete so each issue is a real entry point rather than a placeholder.

## Improve model-configuration error messages

**Labels:** `good-first-issue`, `area: cli`, `enhancement`

Audit settings and onboarding validation. Replace generic failures with actionable, secret-safe guidance for a missing key, unknown provider, unknown model, and unreachable local endpoint. Valid configurations must remain unchanged and focused unit tests must cover the new messages.

## Validate a fresh Ubuntu installation end to end

**Labels:** `good-first-issue`, `area: packaging`, `os: linux`

Run the documented installation, `--help`, `--version`, first-run setup, and one stub-backed task on a clean supported Ubuntu environment. Add an onboarding report under `docs/onboarding_reports/`, include reproduction steps for every failure, and update confirmed documentation or script gaps.

## Publish a reproducible provider compatibility report

**Labels:** `help-wanted`, `area: engine`, `provider-bug`

Test OpenAI, Anthropic, Google, OpenRouter, Ollama, and LM Studio where access is available. Report provider, model, date, OS, model listing, streaming, structured tool calls, cancellation, and a minimal agent task. Label untested cells honestly and split confirmed bugs into focused issues.

## Test Grinta with LM Studio

**Labels:** `help-wanted`, `provider: lmstudio`, `area: engine`

Validate model discovery, streaming, tool calling, cancellation, a read-only task, a small edit/test task, and offline-endpoint guidance against a current LM Studio server. Record exact versions and add a sanitized known-good settings example.

## Record a macOS installation walkthrough

**Labels:** `documentation`, `os: macos`, `area: packaging`

Test a clean supported Python environment, `pipx`, PATH troubleshooting, optional local-model setup, and first launch. Publish copy-pasteable commands, a sanitized onboarding report, and only verified Apple Silicon or Intel differences.

## Contribute a reproducible autonomous coding evaluation

**Labels:** `help-wanted`, `evaluation`, `area: engine`

Add a self-contained task with independently defined tests, a pinned prompt, explicit budgets, and reporting for runtime, model, tokens/cost, tool outcomes, and human intervention. Keep agent `FINISHED` state distinct from external acceptance-test compliance.

## Improve first-run provider selection in the TUI

**Labels:** `help-wanted`, `ux`, `area: cli`, `enhancement`

Make hosted-versus-local choices, credentials, endpoint checks, and a safe test action understandable from a clean state. Preserve keyboard-only navigation and narrow-terminal usability; back and cancel paths must not leave partial secrets or invalid settings.

## Profile context compaction during long sessions

**Labels:** `help-wanted`, `performance`, `area: engine`

Create a repeatable long-session benchmark for compaction duration, prompt size before and after, peak RSS, cache behavior, and retrieval overhead at multiple context-pressure levels. Commit a compact report and require before/after numbers for any optimization.
