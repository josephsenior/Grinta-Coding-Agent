# Proposed Grinta v1.0.0-rc1 Release Notes

These notes are prepared for a future `v1.0.0-rc1` release. That tag and its package artifacts have not been published yet.
The current `main` branch is intended for evaluation and focused feedback before the release candidate is cut.

These notes capture the intended support stance for RC publication.
For the current support contract and CI certification depth, see [SUPPORT_MATRIX.md](SUPPORT_MATRIX.md).

## What this release is

- Proposed RC for the CLI-first open-source product surface.
- Intended for everyday coding workflows on Linux and Windows while we collect final RC feedback.
- Feedback-driven final polish phase before cutting `1.0.0`.

## Highlights

- **CLI-first, local-first architecture** with no managed cloud control plane.
- **Provider-agnostic model routing** across OpenAI, Anthropic, Google, OpenRouter, Ollama, and LM Studio.
- **Textual terminal UI** with Chat, Plan, and Agent workflows.
- **LSP and DAP integrations** discovered from the local development environment.
- **Built-in reliability controls** including stuck-loop detection, recovery prompts, and task validation before finish.
- **Execution safety rails** via risk-classified actions, secret masking, and the `hardened_local` policy profile.
- **Session durability** through event-stream storage with checkpoint/resume/revert workflows.
- **Public execution evidence** including a 4h 33m autonomous session with 16,393 events and 373 tool outcomes.

## Evidence and demos

- [Showcase index](../SHOWCASE.md)
- [4h 33m autonomous execution report](evidence/2026-07-09-autonomous-run-report.md)
- [Raft key-value store demo](assets/grinta-demo.mp4)
- [Animated recovery preview](assets/grinta-demo-preview.webp)

## Notable release-candidate improvements

- Restored symbol-aware reading through the current `read` / `find_symbols` file API.
- Added release polish docs and governance/support materials:
  - `docs/RELEASE_CHECKLIST.md`
  - `docs/REGRESSION_TESTS.md`
  - `docs/SUPPORT_MATRIX.md`
  - `GOVERNANCE.md`
  - `MAINTAINERS.md`
  - `THIRD_PARTY_NOTICES.md`
- Added clean-box smoke install scripts for Linux/macOS/Windows and Docker.
- Clarified autonomy language to `conservative` / `balanced` / `full`.

## Intended platform and support stance at RC publication

- **Supported:** Linux, Windows.
- **Best effort:** macOS (advisory CI; not yet a required gate).
- **Current install path:** editable installation from the source checkout.

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
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git Grinta
cd Grinta
pipx install -e .
grinta init
grinta
```

## GA criteria

GA (`1.0.0`) will be cut after RC feedback is triaged and release gates in
`docs/RELEASE_CHECKLIST.md` are satisfied.
