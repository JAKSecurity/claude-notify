#!/usr/bin/env python3
"""Send an email via Gmail SMTP.

Usage:
    python scripts/send_email.py --subject "Morning Briefing" --body-file data/briefings/2026-03-14.md
    python scripts/send_email.py --subject "Test" --body "Hello world"

Secrets (from OS keyring):
    SMTP_PASS   - Gmail App Password

Config (from .env):
    SMTP_USER   - Gmail address (sender)
    SMTP_TO     - Recipient email address
    SMTP_HOST   - SMTP server (default: smtp.gmail.com)
    SMTP_PORT   - SMTP port (default: 587)
"""

import argparse
import mimetypes
import smtplib
import sys
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

try:
    from secret_store import get_secret, get_config
except ImportError:
    from scripts.secret_store import get_secret, get_config


def markdown_to_html(md_text):
    """Minimal markdown-to-HTML conversion (stdlib only)."""
    import re
    html = md_text
    # Headers
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
    # Bold and italic
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
    # List items
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    # Line breaks for remaining plain lines
    html = re.sub(r"\n\n", r"<br><br>", html)
    return f"<html><body style='font-family: sans-serif;'>{html}</body></html>"


def send_email(subject, body_text, body_html=None, attachments=None):
    """Send email via SMTP. Optional attachments is a list of file paths."""
    smtp_user = get_config("SMTP_USER")
    smtp_pass = get_secret("SMTP_PASS")
    smtp_to = get_config("SMTP_TO", smtp_user)
    smtp_host = get_config("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(get_config("SMTP_PORT", "587"))

    if not smtp_user or not smtp_pass:
        print("Error: SMTP_USER must be in .env and SMTP_PASS must be in keyring", file=sys.stderr)
        sys.exit(1)

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = smtp_to

    # Text/HTML body as alternative sub-part
    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(body_text, "plain"))
    if body_html:
        body_part.attach(MIMEText(body_html, "html"))
    msg.attach(body_part)

    # File attachments
    if attachments:
        for filepath in attachments:
            path = Path(filepath)
            if not path.exists():
                print(f"Warning: attachment not found: {filepath}", file=sys.stderr)
                continue
            with open(path, "rb") as f:
                part = MIMEApplication(f.read(), Name=path.name)
            part["Content-Disposition"] = f'attachment; filename="{path.name}"'
            msg.attach(part)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [smtp_to], msg.as_string())

    print(f"Email sent to {smtp_to}: {subject}")


def main():
    parser = argparse.ArgumentParser(description="Send email via Gmail SMTP")
    parser.add_argument("--subject", required=True, help="Email subject line")
    parser.add_argument("--body", help="Email body text")
    parser.add_argument("--body-file", help="Read body from a markdown file")
    parser.add_argument("--attach", action="append", help="File to attach (can be repeated)")
    args = parser.parse_args()

    if args.body_file:
        body_text = Path(args.body_file).read_text(encoding="utf-8")
        body_html = markdown_to_html(body_text)
    elif args.body:
        body_text = args.body
        body_html = None
    else:
        print("Error: provide --body or --body-file", file=sys.stderr)
        sys.exit(1)

    send_email(args.subject, body_text, body_html, attachments=args.attach)


if __name__ == "__main__":
    main()
