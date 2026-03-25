---
name: SSH Playbook
type: knowledge
version: 2.0.0
agent: Orchestrator
triggers:
  - /ssh
---

# SSH quick reference

## Session

```bash
ssh user@host
ssh -i ~/.ssh/keyname user@host
ssh -p PORT user@host
```

## Keys

```bash
ssh-keygen -t ed25519 -f ~/.ssh/keyname -N ""
ssh-copy-id -i ~/.ssh/keyname.pub user@host
chmod 700 ~/.ssh && chmod 600 ~/.ssh/keyname
```

## Config (`~/.ssh/config`)

```
Host myalias
  HostName host.example.com
  User myuser
  IdentityFile ~/.ssh/keyname
```

## Copy files

```bash
scp file user@host:/path/
scp -r dir user@host:/path/
```

## Debug

`ssh -vvv user@host` — check permissions, firewall, and that `sshd` is running on the server.
