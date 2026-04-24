---
name: security
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /security
  - /audit
  - /owasp
---

# Security audit workflow

Use when the user explicitly invokes **`/security`**, **`/audit`**, or **`/owasp`**.
For general code quality issues, follow system **EXECUTION_DISCIPLINE** first.

## 1. Scope

Identify the attack surface: HTTP endpoints, auth boundaries, data inputs, file I/O, subprocess calls, and third-party integrations. Use `search_code` to enumerate entry points — do not guess.

## 2. OWASP Top 10 pass

| Risk | What to grep / check |
|------|---------------------|
| A01 Broken Access Control | Missing auth decorators, horizontal privilege escalation, path traversal |
| A02 Crypto Failures | Hardcoded secrets, weak hashes (MD5/SHA1), plain-text sensitive storage |
| A03 Injection | Unsanitised SQL/shell/LDAP inputs, f-string queries, `eval`/`exec` |
| A04 Insecure Design | Missing rate limits, no input size caps, unrestricted file upload |
| A05 Security Misconfiguration | Debug mode in prod, permissive CORS, verbose error messages |
| A06 Vulnerable Components | Outdated deps — run `pip audit` / `npm audit` / `trivy` |
| A07 Auth Failures | Weak passwords accepted, session tokens not rotated, JWT `alg=none` |
| A08 Data Integrity | Unsigned dependencies, no SBOM, deserialisation of untrusted data |
| A09 Logging Failures | Missing audit logs, secrets logged, no tamper-evident log store |
| A10 SSRF | User-controlled URLs passed to `requests`/`httpx` without allowlist |

## 3. Findings format

For each finding:
- **Severity**: Critical / High / Medium / Low / Info
- **Location**: file path + line range
- **Description**: what is wrong and why it is exploitable
- **Fix**: minimal concrete change — show before/after snippet

## 4. Fix discipline

- One finding → one atomic fix. Do not bundle unrelated changes.
- Add a regression test for every Critical or High finding where possible.
- After patching, re-run the reproducer or the relevant test suite.

## 5. Done

Full findings list + remediation summary. Flag any Critical findings that require immediate operator action (key rotation, env var changes) that cannot be completed in code alone.
