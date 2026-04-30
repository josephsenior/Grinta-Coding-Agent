# Grinta v1.0.0-rc1 Release Notes (Draft)

`v1.0.0-rc1` is the public release candidate for Grinta's 1.0 line.
This build is intended for real usage and focused feedback before final GA.

## What this release is

- Public RC for the CLI-first open-source product surface.
- Intended for everyday coding workflows on Linux and Windows while we collect final RC feedback.
- Feedback-driven final polish phase before cutting `1.0.0`.

## Highlights

- **CLI-first, local-first architecture** with no managed cloud control plane.
- **Provider-agnostic model routing** across OpenAI, Anthropic, Google, OpenRouter, Ollama, and LM Studio.
- **Built-in reliability controls** including stuck-loop detection, recovery prompts, and task validation before finish.
- **Execution safety rails** via risk-classified actions, secret masking, and the `hardened_local` policy profile.
- **Session durability** through event-stream storage with checkpoint/resume/revert workflows.

## Notable release-candidate improvements

- Restored `read_symbol_definition` as a tree-sitter-backed retrieval primitive.
- Added release polish docs and governance/support materials:
  - `docs/RELEASE_CHECKLIST.md`
  - `docs/REGRESSION_TESTS.md`
  - `docs/SUPPORT_MATRIX.md`
  - `GOVERNANCE.md`
  - `MAINTAINERS.md`
  - `THIRD_PARTY_NOTICES.md`
- Added clean-box smoke install scripts for Linux/macOS/Windows and Docker.
- Clarified autonomy language to `conservative` / `balanced` / `full`.

## Platform and support stance

- **Supported:** Linux, Windows.
- **Best effort:** macOS (advisory CI; not yet a required gate).
- **Preferred install path:** `pipx install grinta-ai`.

## Known limitations and candid caveats

- Grinta runs as your local OS user and is **not** a sandbox.
- `hardened_local` adds policy checks but does not provide process isolation.
- For untrusted repos, use a VM or container you control.

## Feedback requested before GA

We especially want high-signal feedback in these areas:

- First-run install and `grinta init` onboarding friction
- CLI output clarity and command discoverability
- Runtime reliability under long or complex tasks
- Cross-platform behavior differences (especially terminal edge cases)

Please open issues with the `RC Feedback` template:
<https://github.com/josephsenior/Grinta-Coding-Agent/issues/new/choose>

## Upgrade / install

```bash
pipx install grinta-ai
grinta init
grinta
```

## GA criteria

GA (`1.0.0`) will be cut after RC feedback is triaged and release gates in
`docs/RELEASE_CHECKLIST.md` are satisfied.
