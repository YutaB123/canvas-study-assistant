"""Tests for settings loading (esp. what a web-only deploy actually requires)."""

from __future__ import annotations

import pytest

from app.config import load_settings


def test_web_deploy_requires_only_anthropic_and_canvas(monkeypatch):
    # A web-mode deploy (Render) has no Twilio creds — that must NOT crash startup.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CANVAS_TOKEN", "canvas-test")
    monkeypatch.setenv("CHANNEL", "web")
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)

    s = load_settings(require_secrets=True)
    assert s.anthropic_api_key == "sk-test"
    assert s.canvas_token == "canvas-test"
    assert s.twilio_account_sid == ""  # absent is fine in web mode
    assert s.twilio_auth_token == ""


def test_missing_anthropic_key_still_errors(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CANVAS_TOKEN", "canvas-test")
    with pytest.raises(RuntimeError):
        load_settings(require_secrets=True)


def test_public_base_url_falls_back_to_render_external_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("CANVAS_TOKEN", "y")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://canvas-study-assistant.onrender.com")
    s = load_settings(require_secrets=True)
    assert s.public_base_url == "https://canvas-study-assistant.onrender.com"
