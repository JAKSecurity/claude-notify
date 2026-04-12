# claude-notify

## Project Overview
Lightweight notification/delivery toolkit for Claude Code automation. Provides Discord, email, push, and TTS delivery as simple CLI scripts with shared secret management via OS keyring.

## Scripts
- `scripts/send_discord.py` — Discord webhook delivery (auto-chunking, attachments)
- `scripts/send_email.py` — SMTP email with markdown-to-HTML
- `scripts/send_push.py` — ntfy.sh push notifications
- `scripts/generate_tts.py` — Edge TTS markdown-to-audio
- `scripts/secret_store.py` — Shared credential management (keyring + .env)
- `scripts/migrate_secrets.py` — Secret migration/setup utility

## Usage Pattern
All scripts are standalone CLI tools. They share `secret_store.py` which reads secrets from the OS keyring and config from `.env`. No script imports another delivery script — they're independent.

## Key Design Decisions
- Secrets NEVER in config files — OS keyring only (Windows Credential Manager / macOS Keychain / Linux Secret Service)
- Config (SMTP host, port, ntfy server) in `.env` — non-secret, safe to template
- Each script handles its own error reporting to stderr
- Discord messages auto-chunk on paragraph boundaries at 1950 chars
- TTS preprocessing expands abbreviations (F→degrees, mph→miles per hour, compass directions)
- Import fallback pattern (`from secret_store` / `from scripts.secret_store`) supports both direct execution and package import

## Dependencies
- `requests` — HTTP for Discord and ntfy
- `keyring` — OS credential storage
- `edge-tts` — Microsoft Edge TTS (for generate_tts.py only)
- Python stdlib only for email (smtplib, email.mime)
