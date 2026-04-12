# claude-notify

A lightweight notification and delivery toolkit for Claude Code automation projects. Send messages through Discord webhooks, email (SMTP), push notifications (ntfy.sh), and generate TTS audio from markdown.

## Features

- **Discord** — Webhook delivery with auto-chunking for long messages, file attachments (MP3, PDF, etc.)
- **Email** — SMTP delivery with markdown-to-HTML conversion and attachments
- **Push** — ntfy.sh notifications with priority levels
- **TTS** — Edge TTS audio generation from markdown with speech preprocessing (abbreviation expansion, compass directions, temperature units)
- **Secrets** — OS keyring integration (no credentials in config files)

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy config template
cp .env.example .env
# Edit .env with your SMTP and ntfy settings

# Store secrets in OS keyring
python scripts/migrate_secrets.py --set SMTP_PASS "your-app-password"
python scripts/migrate_secrets.py --set DISCORD_WEBHOOK "https://discord.com/api/webhooks/..."
python scripts/migrate_secrets.py --set NTFY_TOPIC "your-topic-name"

# Verify secrets stored correctly
python scripts/migrate_secrets.py --verify
```

## Usage

```bash
# Discord
python scripts/send_discord.py "Hello world"
python scripts/send_discord.py --title "Report" --file report.md --attach report.pdf
python scripts/send_discord.py --webhook-name DISCORD_ALT_WEBHOOK --file update.md

# Email
python scripts/send_email.py --subject "Daily Report" --body-file report.md
python scripts/send_email.py --subject "Alert" --body "Something happened" --attach log.txt

# Push notification
python scripts/send_push.py "Build Complete"
python scripts/send_push.py "ALERT" "Server disk full" --priority high

# TTS audio
python scripts/generate_tts.py briefing.md                    # outputs briefing.mp3
python scripts/generate_tts.py briefing.md --voice en-US-GuyNeural
```

## Architecture

```
scripts/
  secret_store.py      — Shared secrets/config module (keyring + .env)
  send_discord.py      — Discord webhook delivery
  send_email.py        — SMTP email delivery
  send_push.py         — ntfy.sh push notifications
  generate_tts.py      — Edge TTS audio generation
  migrate_secrets.py   — Secret migration utility
```

All scripts share `secret_store.py` for credential management:
- **Secrets** (passwords, tokens, webhook URLs) → OS keyring via `keyring` library
- **Config** (hostnames, ports, non-secret settings) → `.env` file

## Secret Management

Secrets never touch the filesystem. They're stored in the OS credential manager:

| Secret | Description |
|--------|-------------|
| `SMTP_PASS` | SMTP password or app password |
| `DISCORD_WEBHOOK` | Discord webhook URL |
| `NTFY_TOPIC` | ntfy.sh topic name |
| `DISCORD_TOKEN` | Discord bot token (optional) |
| `GOOGLE_MAPS_API_KEY` | Google Maps API key (optional) |

## License

MIT
