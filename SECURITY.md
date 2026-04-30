# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability in Grinta, please report it
responsibly. **Do not** open a public issue, discussion, or pull request that
describes an unpatched vulnerability.

### How to report

1. **Preferred** — open a private GitHub Security Advisory:
   <https://github.com/josephsenior/Grinta-Coding-Agent/security/advisories/new>
2. **Email** — `security@app.ai` (PGP optional, plain text accepted).
3. Include:
   - Description of the vulnerability and affected component(s).
   - Steps to reproduce, ideally with a minimal repository or prompt.
   - Potential impact (data exfiltration, code execution, privilege boundary,
     supply-chain, etc.).
   - Affected version (`grinta --version`) and OS.
   - Suggested fix or mitigation, if any.

### Response timeline

- **Acknowledgement**: within 48 hours.
- **Triage and severity assessment**: within 1 week.
- **Fix and coordinated disclosure**: critical issues within 2 weeks; lower
  severities tracked in the next maintenance release.
- **Credit**: reporters are credited in the release notes unless they request
  otherwise.

### Safe harbour

Good-faith security research that follows this policy will not be pursued.
Please avoid privacy violations, data destruction, denial of service against
shared infrastructure, and access to systems you do not own.

## Supported versions

Only the most recent minor release line receives security fixes. Earlier
versions are best-effort.

| Version | Supported          |
| ------- | ------------------ |
| 0.56.x  | :white_check_mark: |
| < 0.56  | :x:                |

## Security architecture

Grinta is a **local-first** developer tool that runs with the privileges of the
user invoking it. The threat model, built-in protections, and out-of-scope
attacks are documented in detail in
[docs/SECURITY_CHECKLIST.md](docs/SECURITY_CHECKLIST.md). The summary below
captures the boundaries operators care about most.

### Trust boundary

- The agent runs inside the same OS user as the operator. There is **no**
  sandbox, container, namespace, or process isolation.
- Pointing Grinta at an untrusted repository is equivalent to executing that
  repository’s build scripts under your account. Treat it accordingly.
- The local LLM provider, MCP servers, and any plugins you enable are part of
  the trusted compute base.

### Runtime safety

- **Risk classifier (`SecurityAnalyzer` / `command_analyzer.py`)** assigns every
  proposed shell action a NONE / LOW / MEDIUM / HIGH / CRITICAL band before
  execution.
- **Hard CRITICAL refusal gate** in `safety_validator.py::_should_block_action`
  blocks CRITICAL actions regardless of profile, model, or autonomy level.
- **`hardened_local` execution profile** scopes git, package, and network-
  capable commands to the active workspace, with workspace-rooted cwd checks
  for terminal sessions, file uploads, and direct file access.
- **Pattern-based shell guard** detects `rm -rf /`, force pushes to protected
  branches, encoded payloads, privilege escalation, and common exfiltration
  shapes.
- **Circuit breakers and stuck detection** halt the agent on error-rate
  spikes, repeated tool failures, monologue loops, and runaway token /
  cost-acceleration patterns.
- **Per-task budget guards** cap token spend and wall-clock time to limit
  blast radius from prompt injection or model misbehaviour.

### Secrets

- Secrets in `settings.json` should be referenced via `${ENV_VAR}` indirection;
  the canonical secret source is your shell environment, OS keychain, or `.env`
  file — not the JSON itself.
- The **secret masker** strips known secret patterns (provider API keys, JWTs,
  cloud credentials) from event-stream output, audit logs, and panel renders
  before display.
- Audit logs may still capture sensitive content from tool output. Treat
  `~/.grinta/workspaces/<id>/storage/<session>/audit/` as confidential.

### Network and transport

- The default runtime makes **no outbound calls** beyond the LLM endpoint(s)
  you configure and the MCP servers you enable.
- Telemetry and crash reporting are **off by default** and require explicit
  opt-in. See `backend/telemetry/`.
- The legacy local web surface — when enabled — restricts CORS to localhost,
  ships strict security headers, and supports CSRF protection via
  `APP_CSRF_ENABLED`. The supported interactive surface for 0.56 is the CLI.

### Data storage

- File-based storage (default): all session state, ledgers, audit logs, and
  checkpoints stay on the local disk under `~/.grinta/`.
- PostgreSQL (optional): connections use `asyncpg` with pool management; you
  are responsible for transport encryption and credential management.
- Workspace data is never uploaded to a third party by Grinta itself.

### Supply chain

- Builds use [`hatchling`](https://hatch.pypa.io/) and a pinned `uv.lock`.
- Dependencies are scanned via Dependabot; security-relevant updates are
  prioritised in the next patch release.
- Release artefacts (PyPI sdist + wheel, Homebrew formula, Scoop manifest)
  publish a SHA256 in their metadata. Verify before installing in sensitive
  environments.

## Operator checklist

Before running Grinta against an unfamiliar repository:

1. Read [docs/SECURITY_CHECKLIST.md](docs/SECURITY_CHECKLIST.md).
2. Set `security.execution_profile = "hardened_local"` in `settings.json`.
3. Lower autonomy with `/autonomy conservative` for the first few interactions.
4. Confirm a clean `git status` so the post-session diff is meaningful.
5. Review the audit log after the session ends.
