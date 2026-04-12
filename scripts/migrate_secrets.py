#!/usr/bin/env python3
"""One-time migration: move secrets from .env to Windows Credential Manager.

Usage:
    python scripts/migrate_secrets.py              # migrate and rewrite .env
    python scripts/migrate_secrets.py --dry-run    # preview only
    python scripts/migrate_secrets.py --set NTFY_TOPIC myvalue   # set one secret manually
"""

import argparse
import sys
from pathlib import Path

try:
    from secret_store import SERVICE_NAME, SECRET_KEYS, get_secret, set_secret
except ImportError:
    from scripts.secret_store import SERVICE_NAME, SECRET_KEYS, get_secret, set_secret


def parse_env(env_path):
    """Parse .env into (secrets_dict, remaining_lines)."""
    secrets = {}
    remaining = []

    with open(env_path) as f:
        for line in f:
            raw = line.rstrip("\n")
            stripped = raw.strip()

            if not stripped or stripped.startswith("#") or "=" not in stripped:
                remaining.append(raw)
                continue

            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")

            if key in SECRET_KEYS:
                secrets[key] = value
            else:
                remaining.append(raw)

    return secrets, remaining


def migrate(env_path, dry_run=False):
    """Migrate secrets from .env to keyring."""
    if not env_path.exists():
        print("No .env file found. Nothing to migrate.", file=sys.stderr)
        return False

    secrets, remaining = parse_env(env_path)

    if not secrets:
        print("No secrets found in .env. Already migrated?")
        return True

    print(f"Found {len(secrets)} secret(s) to migrate:")
    for key in sorted(secrets):
        masked = secrets[key][:4] + "..." if len(secrets[key]) > 4 else "***"
        print(f"  {key} = {masked}")

    if dry_run:
        print("\n[DRY RUN] No changes made.")
        return True

    for key, value in secrets.items():
        set_secret(key, value)
        print(f"  -> Stored {key} in Windows Credential Manager")

    with open(env_path, "w", newline="\n") as f:
        f.write("\n".join(remaining) + "\n")

    config_count = len([l for l in remaining if l.strip() and not l.strip().startswith("#")])
    print(f"\nDone. {len(secrets)} secret(s) moved to keyring.")
    print(f".env rewritten with {config_count} config value(s) remaining.")
    return True


def verify():
    """Verify all secrets are readable from keyring."""
    print("Verifying keyring secrets:")
    all_ok = True
    for key in sorted(SECRET_KEYS):
        val = get_secret(key)
        if val:
            masked = val[:4] + "..." if len(val) > 4 else "***"
            print(f"  {key} = {masked}")
        else:
            print(f"  {key} = (not set)")
            if key not in ("DISCORD_TOKEN", "GOOGLE_MAPS_API_KEY"):  # optional keys
                all_ok = False
    return all_ok


def main():
    parser = argparse.ArgumentParser(
        description="Migrate secrets from .env to Windows Credential Manager"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    parser.add_argument("--verify", action="store_true", help="Check keyring has all secrets")
    parser.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"),
                        help="Manually set one secret in keyring")
    args = parser.parse_args()

    if args.set:
        key, value = args.set
        if key not in SECRET_KEYS:
            print(f"Warning: {key} is not a known secret key. Known: {sorted(SECRET_KEYS)}")
        set_secret(key, value)
        print(f"Stored {key} in keyring.")
        return

    if args.verify:
        ok = verify()
        sys.exit(0 if ok else 1)

    env_path = Path(__file__).resolve().parent.parent / ".env"
    ok = migrate(env_path, dry_run=args.dry_run)
    if ok and not args.dry_run:
        print()
        verify()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
