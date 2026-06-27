# Grinta documentation

Choose a path:

| Goal | Start here |
| --- | --- |
| Install and run the terminal app, configure models | [Quick Start](QUICK_START.md), [Install](INSTALL.md), [User Guide](USER_GUIDE.md), [settings.json reference](SETTINGS.md) |
| **Windows, Git Bash, or WSL** | [Windows and WSL](WINDOWS_AND_WSL.md) |
| Debug failures and platform issues | [Troubleshooting](TROUBLESHOOTING.md), [Support Matrix](SUPPORT_MATRIX.md) |
| Understand the system or contribute code | [Contributor Map](CONTRIBUTOR_MAP.md), [Architecture](ARCHITECTURE.md), [Developer Guide](DEVELOPER.md), [Vocabulary](VOCABULARY.md), [CI](CI.md), [Contributing](../CONTRIBUTING.md) |
| Maintain releases and keep docs honest | [Release Checklist](RELEASE_CHECKLIST.md), [Fresh Machine Onboarding](FRESH_MACHINE_ONBOARDING.md), [Roadmap](../ROADMAP.md) |

## The Book of Grinta (narrative — not a spec)

Long-form engineering memoir: **[journey/README.md](journey/README.md)**. These chapters are **historical narrative only**. They may describe removed features, old autonomy branching, or pre-RC architecture. **Do not use `docs/journey/` as a configuration or behavior reference.** For current behavior use [USER_GUIDE.md](USER_GUIDE.md), [SETTINGS.md](SETTINGS.md), and [ARCHITECTURE.md](ARCHITECTURE.md).

## More reference

| Topic | Doc |
| --- | --- |
| Agent engines and tool surface | [ENGINES.md](ENGINES.md) |
| LLM providers vs MCP vs native tools | [INFERENCE_AND_INTEGRATIONS.md](INFERENCE_AND_INTEGRATIONS.md) |
| File editing tools (`read`, `edit_symbol`, …) | [TWO_MODE_FILE_EDITING.md](TWO_MODE_FILE_EDITING.md) |
| Reliability, timeouts | [RELIABILITY.md](RELIABILITY.md) |
| Performance | [PERFORMANCE.md](PERFORMANCE.md) |
| Security checklist | [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md) |
| Terminal UI and themes | [CLI_THEME_CONTRACT.md](CLI_THEME_CONTRACT.md) |
| Plugins | [PLUGIN_GUIDE.md](PLUGIN_GUIDE.md), [plugins/authoring_guide.md](plugins/authoring_guide.md) |
| MCP integration | [MCP_EXAMPLES.md](MCP_EXAMPLES.md), [mcp/integration_examples.md](mcp/integration_examples.md) |
| Release / GA gates | [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md), [FRESH_MACHINE_ONBOARDING.md](FRESH_MACHINE_ONBOARDING.md) |
| ADRs | [ADR.md](ADR.md) |

The repository root [README.md](../README.md) links here and to the rest of the project.

Current-product rule of thumb: root docs and the top-level docs pages describe the supported surface; `docs/journey/` is historical narrative and may describe behavior that has since changed.
