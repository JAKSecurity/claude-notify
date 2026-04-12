#!/usr/bin/env python3
"""Send push notification via ntfy.sh.

Usage:
    python scripts/send_push.py "Title" "Message body"
    python scripts/send_push.py "Briefing Ready"

Secrets (from OS keyring):
    NTFY_TOPIC  - ntfy.sh topic name

Config (from .env):
    NTFY_SERVER - ntfy server URL (default: https://ntfy.sh)
"""

import argparse
import sys

import requests

try:
    from secret_store import get_secret, get_config
except ImportError:
    from scripts.secret_store import get_secret, get_config


def send_push(title, message=None, priority="default"):
    """Send a push notification via ntfy.sh."""
    server = get_config("NTFY_SERVER", "https://ntfy.sh")
    topic = get_secret("NTFY_TOPIC")

    if not topic:
        print("Error: NTFY_TOPIC not found in keyring or environment", file=sys.stderr)
        sys.exit(1)

    resp = requests.post(
        f"{server}/{topic}",
        data=message or title,
        headers={"Title": title, "Priority": priority},
    )
    resp.raise_for_status()
    print(f"Push sent: {title}")


def main():
    parser = argparse.ArgumentParser(description="Send push notification via ntfy.sh")
    parser.add_argument("title", help="Notification title")
    parser.add_argument("message", nargs="?", help="Message body (defaults to title)")
    parser.add_argument("--priority", "-p", default="default",
                        help="Priority: default, high, urgent")
    args = parser.parse_args()

    send_push(args.title, args.message, args.priority)


if __name__ == "__main__":
    main()
