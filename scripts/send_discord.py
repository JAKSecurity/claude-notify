#!/usr/bin/env python3
"""Send a message to a Discord channel via webhook.

Usage:
    python scripts/send_discord.py "Message content"
    python scripts/send_discord.py --file data/briefings/2026-03-15.md
    python scripts/send_discord.py --title "Morning Briefing" --file data/briefings/2026-03-15.md
    python scripts/send_discord.py --title "Briefing" --file briefing.md --attach briefing.mp3
    python scripts/send_discord.py --webhook-name DISCORD_SPECTRA_WEBHOOK --title "SPECTRA" --file report.md

Secrets (from OS keyring):
    DISCORD_WEBHOOK          - Default Discord webhook URL
    DISCORD_SPECTRA_WEBHOOK  - SPECTRA channel webhook URL (optional)
"""

import argparse
import json
import sys
from pathlib import Path

import requests

try:
    from secret_store import get_secret
except ImportError:
    from scripts.secret_store import get_secret


def send_discord(content, webhook_url):
    """Send a message to Discord via webhook. Handles chunking for long messages."""
    # Discord limit is 2000 chars per message
    MAX_LEN = 1950

    chunks = []
    if len(content) <= MAX_LEN:
        chunks = [content]
    else:
        # Split on paragraph boundaries
        paragraphs = content.split("\n\n")
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 2 > MAX_LEN:
                if current:
                    chunks.append(current)
                # If a single paragraph exceeds limit, hard-truncate
                if len(para) > MAX_LEN:
                    chunks.append(para[:MAX_LEN])
                else:
                    current = para
            else:
                current = current + "\n\n" + para if current else para
        if current:
            chunks.append(current)

    for i, chunk in enumerate(chunks):
        resp = requests.post(
            webhook_url,
            json={"content": chunk},
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        if resp.status_code not in (200, 204):
            print(f"Discord error (chunk {i+1}): {resp.status_code} {resp.text}", file=sys.stderr)
            return False

    return True


def send_attachment(file_path, webhook_url):
    """Send a file attachment to Discord via webhook."""
    with open(file_path, "rb") as f:
        resp = requests.post(
            webhook_url,
            files={"file": (file_path.name, f)},
        )
    if resp.status_code not in (200, 204):
        print(f"Discord attachment error: {resp.status_code} {resp.text}", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Send message to Discord webhook")
    parser.add_argument("message", nargs="?", help="Message text")
    parser.add_argument("--file", "-f", help="Read message from file")
    parser.add_argument("--title", "-t", help="Bold title prepended to message")
    parser.add_argument("--attach", "-a", help="File to attach (e.g., MP3 audio, PDF)")
    parser.add_argument("--webhook-name", "-w", default="DISCORD_WEBHOOK",
                        help="Keyring secret name for webhook URL (default: DISCORD_WEBHOOK)")
    args = parser.parse_args()

    webhook = get_secret(args.webhook_name)
    if not webhook:
        print(f"Error: {args.webhook_name} not found in keyring or environment", file=sys.stderr)
        sys.exit(1)

    if args.file:
        content = Path(args.file).read_text(encoding="utf-8")
    elif args.message:
        content = args.message
    else:
        print("Error: provide a message or --file", file=sys.stderr)
        sys.exit(1)

    if args.title:
        content = f"**{args.title}**\n\n{content}"

    # Send file attachment if provided
    if args.attach:
        attach_path = Path(args.attach)
        if attach_path.exists():
            if send_attachment(attach_path, webhook):
                print(f"Discord attachment sent: {attach_path.name}")
            else:
                print(f"Discord attachment failed: {attach_path.name}", file=sys.stderr)
        else:
            print(f"Attachment not found: {args.attach}", file=sys.stderr)

    if send_discord(content, webhook):
        print("Discord message sent.")
    else:
        print("Discord delivery failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
