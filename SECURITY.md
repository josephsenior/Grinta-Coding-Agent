# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability in App, please report it responsibly.

**DO NOT** open a public issue for security vulnerabilities.

### How to Report

1. Email: security@app.ai (or open a private security advisory on GitHub)
2. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Assessment**: Within 1 week
- **Fix**: Critical issues within 2 weeks

## Supported Versions

| Version | Supported |
|---|---|
| 0.55.x | Yes |
| < 0.55 | No |

## Security Architecture

### Transport
- CORS restricted to localhost by default
- CSRF protection available (opt-in via `APP_CSRF_ENABLED`)
- Security headers (CSP, X-Frame-Options, etc.) via middleware

### Runtime Safety
- Command analysis before execution (`SecurityAnalyzer`)
- Optional `hardened_local` execution profile for stricter local policy enforcement
- Budget guards to prevent runaway LLM costs
- Circuit breakers for error rate protection
- Request size limits and timeouts

### Runtime Boundary
- App does not currently provide sandbox or container isolation for local command execution.
- The local runtime executes with the permissions of the user running App.
- `hardened_local` improves local safety with workspace-scoped policy enforcement, but it is not equivalent to a sandbox.
- Treat the current runtime as appropriate for trusted local development workflows, not hostile repositories.

### Data Storage
- File-based storage (default): data stays on your machine
- PostgreSQL (optional): connections use `asyncpg` with pool management
- No telemetry sent without explicit opt-in
