---
name: net_diag
type: knowledge
version: 1.1.0
agent: Orchestrator
triggers:
  - /net
  - /network
---

# Network diagnostics

Troubleshoot DNS, TLS, HTTP, and connectivity issues.

## DNS resolution

```bash
# Basic lookup
nslookup example.com
Resolve-DnsName example.com

# Query specific record types
Resolve-DnsName example.com -Type MX
Resolve-DnsName example.com -Type TXT

# Check which DNS server answered
nslookup example.com $(Get-DnsClientServerAddress -AddressFamily IPv4).ServerAddresses[0]
```

## TLS and certificates

```bash
# Inspect certificate chain
openssl s_client -connect api.example.com:443 -showcerts

# Check expiration
echo | openssl s_client -connect api.example.com:443 2>/dev/null | \
  openssl x509 -noout -dates

# Test with specific TLS version
openssl s_client -connect api.example.com:443 -tls1_2
```

## HTTP debugging

```bash
# Headers only
curl -sI https://api.example.com

# Full response with status code
curl -sv https://api.example.com 2>&1 | head -40

# POST with JSON body (common for LLM APIs)
curl -sv https://api.example.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -d '{"model":"test","messages":[{"role":"user","content":"hi"}]}'

# Time a request
curl -w "dns: %{time_namelookup}s\nconnect: %{time_connect}s\nssl: %{time_appconnect}s\ntotal: %{time_total}s\n" \
  -so /dev/null https://api.example.com
```

## Connectivity

```bash
# TCP port check
Test-NetConnection api.example.com -Port 443

# Traceroute
tracert api.example.com
Test-NetConnection api.example.com -TraceRoute

# Check firewall / proxy
curl -sv --proxy http://proxy:8080 https://api.example.com
```

## Common issues

| Symptom | Likely cause | Check |
|---------|-------------|-------|
| `Could not resolve host` | DNS failure or typo | `nslookup`, `Resolve-DnsName` |
| `Connection timed out` | Firewall, wrong port, routing | `Test-NetConnection -Port` |
| `SSL certificate expired` | Cert renewal missed | `openssl s_client` |
| `Connection reset` | Proxy, TLS version mismatch | `curl -sv`, proxy env vars |
| `403 Forbidden` | Auth or IP allowlist | `curl -sv`, check headers |

## Example: debug an LLM API endpoint

```bash
curl -sv "https://$BASE_URL/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"model":"$MODEL","messages":[{"role":"user","content":"ping"}]}' \
  -w "\n---\ntime: %{time_total}s\ncode: %{http_code}\n"
```
