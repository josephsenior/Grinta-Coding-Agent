# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability in Forge, please report it responsibly.

**DO NOT** open a public issue for security vulnerabilities.

### How to Report

1. Email: security@forge.ai (or open a private security advisory on GitHub)
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
- CSRF protection available (opt-in via `FORGE_CSRF_ENABLED`)
- Security headers (CSP, X-Frame-Options, etc.) via middleware

### Runtime Safety
- Command analysis before execution (`SecurityAnalyzer`)
- Budget guards to prevent runaway LLM costs
- Circuit breakers for error rate protection
- Request size limits and timeouts

### Data Storage
- File-based storage (default): data stays on your machine
- PostgreSQL (optional): connections use `asyncpg` with pool management
- No telemetry sent without explicit opt-in
