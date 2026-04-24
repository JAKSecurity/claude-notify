"""Tests for [AI Assistant #051 follow-up] Discord attachment size verification.

Verifies that send_attachment:
  - appends ?wait=true to the webhook URL so Discord returns the message
  - compares local file size to Discord's stored attachment size
  - returns False on size mismatch (Discord-side truncation)
  - returns True on clean upload
  - never raises on malformed / missing metadata (logs and trusts status code)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from send_discord import send_attachment  # noqa: E402


@pytest.fixture
def sample_mp3(tmp_path):
    f = tmp_path / "briefing.mp3"
    f.write_bytes(b"\x00" * 1000)
    return f


def _mock_response(status=200, json_body=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.json.return_value = json_body or {}
    return resp


def test_send_attachment_appends_wait_true_to_url(sample_mp3):
    with patch("send_discord.requests.post") as mock_post:
        mock_post.return_value = _mock_response(200, {"attachments": [{"size": 1000}]})
        send_attachment(sample_mp3, "https://discord.example/webhook/abc")
        called_url = mock_post.call_args[0][0]
        assert "wait=true" in called_url


def test_send_attachment_respects_existing_query_params(sample_mp3):
    with patch("send_discord.requests.post") as mock_post:
        mock_post.return_value = _mock_response(200, {"attachments": [{"size": 1000}]})
        send_attachment(sample_mp3, "https://discord.example/webhook/abc?foo=bar")
        called_url = mock_post.call_args[0][0]
        assert called_url.endswith("&wait=true")


def test_send_attachment_returns_true_on_size_match(sample_mp3, capsys):
    with patch("send_discord.requests.post") as mock_post:
        mock_post.return_value = _mock_response(200, {"attachments": [{"size": 1000}]})
        result = send_attachment(sample_mp3, "https://discord.example/webhook/abc")
    assert result is True
    assert "verified" in capsys.readouterr().err


def test_send_attachment_returns_false_on_size_mismatch(sample_mp3, capsys):
    with patch("send_discord.requests.post") as mock_post:
        mock_post.return_value = _mock_response(
            200, {"attachments": [{"size": 600}]}  # Discord only stored 600 of 1000
        )
        result = send_attachment(sample_mp3, "https://discord.example/webhook/abc")
    assert result is False
    err = capsys.readouterr().err
    assert "SIZE MISMATCH" in err
    assert "local=1000" in err
    assert "stored=600" in err


def test_send_attachment_returns_true_when_no_attachments_in_response(sample_mp3, capsys):
    """Webhook succeeded (200) but no attachment metadata — trust the status."""
    with patch("send_discord.requests.post") as mock_post:
        mock_post.return_value = _mock_response(200, {})
        result = send_attachment(sample_mp3, "https://discord.example/webhook/abc")
    assert result is True
    assert "cannot verify" in capsys.readouterr().err


def test_send_attachment_returns_true_when_size_missing(sample_mp3, capsys):
    """Attachment present but no size field — still trust the status."""
    with patch("send_discord.requests.post") as mock_post:
        mock_post.return_value = _mock_response(200, {"attachments": [{}]})
        result = send_attachment(sample_mp3, "https://discord.example/webhook/abc")
    assert result is True
    assert "cannot verify" in capsys.readouterr().err


def test_send_attachment_returns_false_on_http_error(sample_mp3, capsys):
    with patch("send_discord.requests.post") as mock_post:
        mock_post.return_value = _mock_response(413, text="Payload Too Large")
        result = send_attachment(sample_mp3, "https://discord.example/webhook/abc")
    assert result is False
    assert "413" in capsys.readouterr().err


def test_send_attachment_swallows_json_parse_error(sample_mp3, capsys):
    """If Discord returns 200 but non-JSON body, log and return True — don't
    fail on parse since the upload itself succeeded.
    """
    with patch("send_discord.requests.post") as mock_post:
        resp = _mock_response(200)
        resp.json.side_effect = ValueError("not JSON")
        mock_post.return_value = resp
        result = send_attachment(sample_mp3, "https://discord.example/webhook/abc")
    assert result is True
    assert "parse error" in capsys.readouterr().err
