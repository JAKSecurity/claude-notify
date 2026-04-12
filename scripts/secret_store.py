"""Shared secrets and config module.

Secrets are stored in the Windows Credential Manager via the `keyring` library.
Non-secret config values are read from the project .env file.

Usage:
    from secret_store import get_secret, get_config

    smtp_pass = get_secret("SMTP_PASS")          # from keyring
    smtp_host = get_config("SMTP_HOST", "smtp.gmail.com")  # from .env
"""

import os
from pathlib import Path

import keyring

SERVICE_NAME = "claude-notify"

SECRET_KEYS = frozenset({
    "SMTP_PASS",
    "NTFY_TOPIC",
    "DISCORD_WEBHOOK",
    "DISCORD_TOKEN",
    "GOOGLE_MAPS_API_KEY",
})

_env_cache: dict[str, str] | None = None


def _env_path() -> Path:
    """Return the path to the project .env file."""
    return Path(__file__).resolve().parent.parent / ".env"


def _load_env_file(path: Path | None = None) -> dict[str, str]:
    """Parse a .env file into a dict. Skips comments and blank lines."""
    if path is None:
        path = _env_path()
    if not path.exists():
        return {}
    result = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip("\"'")
    return result


def _get_env_config() -> dict[str, str]:
    """Return cached .env config, parsing file on first call."""
    global _env_cache
    if _env_cache is None:
        _env_cache = _load_env_file()
    return _env_cache


def get_secret(name: str) -> str | None:
    """Get a secret. Checks environment variable first, then OS keyring."""
    val = os.environ.get(name)
    if val is not None:
        return val
    return keyring.get_password(SERVICE_NAME, name)


def get_config(name: str, default: str | None = None) -> str | None:
    """Get a config value. Checks env var first, then .env file, then default."""
    val = os.environ.get(name)
    if val is not None:
        return val
    config = _get_env_config()
    return config.get(name, default)


def set_secret(name: str, value: str) -> None:
    """Store a secret in the OS keyring."""
    keyring.set_password(SERVICE_NAME, name, value)
