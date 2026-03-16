---
name: SSH Playbook
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /ssh
  - ssh
  - ssh-keygen
  - ssh keys
---

# SSH Guide

## Quick Commands

```bash
# Connect
ssh username@hostname

# With key
ssh -i ~/.ssh/key_name username@hostname

# Generate key
ssh-keygen -t ed25519 -f ~/.ssh/key_name -N ""

# Copy key to server
ssh-copy-id -i ~/.ssh/key_name.pub username@hostname
```

## SSH Config

```bash
# ~/.ssh/config
Host alias
    HostName hostname_or_ip
    User username
    IdentityFile ~/.ssh/key_name
    Port 22

# Then: ssh alias
```

## File Transfer

```bash
# To remote
scp file.txt user@host:/path/

# From remote
scp user@host:/path/file.txt ./

# Directory
scp -r ./dir user@host:/path/
```

## Common Options

- `-p PORT` - Custom port
- `-L local:remote:port` - Local port forward
- `-v` - Verbose (debug)

## Troubleshooting

```bash
# Debug connection
ssh -vvv user@host

# Fix permissions
chmod 700 ~/.ssh
chmod 600 ~/.ssh/id_ed25519
chmod 644 ~/.ssh/id_ed25519.pub

# Check service
systemctl status sshd

# Test port
nc -zv hostname 22
```
