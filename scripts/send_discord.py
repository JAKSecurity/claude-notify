#!/usr/bin/env python3
"""Send a message to a Discord channel via webhook.

Usage:
    python scripts/send_discord.py "Message content"
    python scripts/send_discord.py --file data/briefings/2026-03-15.md
    python scripts/send_discord.py --title "Morning Briefing" --file data/briefings/2026-03-15.md
    python scripts/send_discord.py --title "Briefing" --file briefing.md --attach briefing.mp3
    python scripts/send_discord.py --webhook-name DISCORD_ALT_WEBHOOK --title "Report" --file report.md

Secrets (from OS keyring):
    DISCORD_WEBHOOK          - Default Discord webhook URL
    (additional webhooks can be stored with custom names)
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
    """Send a file attachment to Discord via webhook.

    Verifies that the byte count Discord stored matches the local file size by
    requesting the message object back via `?wait=true` and inspecting the
    `attachments[].size` field. Mismatch is logged and the function returns
    False so the caller can alert.

    Why: AI Assistant ticket [051] — briefing MP3s were reportedly cut off on
    the Discord side even though on-disk files were complete. Without this
    check, a silent Discord-side truncation (size-limit proxy, network hiccup)
    looks identical to a clean upload because the webhook still returns 200.
    """
    local_size = file_path.stat().st_size
    # wait=true makes Discord return the created message (including
    # attachment metadata) instead of a bare 204. We need that metadata to
    # verify size.
    sep = "&" if "?" in webhook_url else "?"
    verify_url = f"{webhook_url}{sep}wait=true"

    with open(file_path, "rb") as f:
        resp = requests.post(
            verify_url,
            files={"file": (file_path.name, f)},
        )
    if resp.status_code not in (200, 204):
        print(f"Discord attachment error: {resp.status_code} {resp.text}", file=sys.stderr)
        return False

    # Parse response and verify stored size. Any parse error is logged but
    # does NOT fail the caller — the upload itself succeeded per 200/204.
    try:
        msg = resp.json()
        attachments = msg.get("attachments") or []
        if not attachments:
            print(
                f"[discord][{file_path.name}] upload OK but no attachments in "
                f"response; cannot verify size",
                file=sys.stderr,
            )
            return True
        stored_size = attachments[0].get("size")
        if stored_size is None:
            print(
                f"[discord][{file_path.name}] upload OK but attachment missing "
                f"size field; cannot verify",
                file=sys.stderr,
            )
            return True
        if stored_size != local_size:
            delta = local_size - stored_size
            pct = 100.0 * stored_size / local_size if local_size else 0
            print(
                f"[discord][{file_path.name}] SIZE MISMATCH — "
                f"local={local_size} stored={stored_size} "
                f"delta={delta} ({pct:.1f}% uploaded)",
                file=sys.stderr,
            )
            return False
        print(
            f"[discord][{file_path.name}] upload verified: {stored_size} bytes",
            file=sys.stderr,
        )
    except Exception as e:
        print(
            f"[discord][{file_path.name}] verification parse error: {e!r}; "
            f"not failing (upload status was {resp.status_code})",
            file=sys.stderr,
        )
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
