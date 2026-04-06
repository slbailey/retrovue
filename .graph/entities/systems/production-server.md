# Production Server

**Domain:** systems  
**Slug:** `production-server`

## What it represents

The production deployment environment for RetroVue.

## Connection details

- **Host:** 192.168.1.199
- **SSH user:** steve
- **SSH access:** `ssh steve@192.168.1.199`
- **RetroVue install path:** `/opt/retrovue`
- **Auth method:** SSH key (`ssh-ed25519`, key comment `steve@paperclip`)

## Key services on production

- RetroVue Core (Python) — scheduling, playout orchestration
- RetroVue AIR (C++) — playout engine, encode/mux

## Log access

- Core logs: `journalctl -u retrovue-core` or stdout/stderr from the running process
- AIR logs: stderr from the AIR process or journalctl if systemd-managed
- Log directory (if configured): `/opt/retrovue/logs/`

## Notes

- All agents may SSH to this host for troubleshooting when assigned a production debugging task.
- Always use the SSH key at `~/.ssh/id_ed25519` (ed25519, `steve@paperclip`) — already authorized on the server.
