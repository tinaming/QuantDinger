"""Tests for email verification send helpers."""
import os

import pytest


def test_send_email_reports_missing_smtp_config(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("SMTP_USER", "")
    monkeypatch.setenv("SMTP_PASSWORD", "")

    from app.services import email_service as mod

    monkeypatch.setattr(mod, "_email_service", None)
    svc = mod.get_email_service()
    assert svc.is_configured() is False
    ok, msg = svc.send_email("user@example.com", "subj", "<p>hi</p>")
    assert ok is False
    assert "SMTP_HOST" in msg
    assert "SMTP_USER" in msg
    assert "SMTP_PASSWORD" in msg


def test_send_email_uses_ssl_timeout(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "user@example.com")
    monkeypatch.setenv("SMTP_USE_SSL", "true")
    monkeypatch.setenv("SMTP_USE_TLS", "false")
    monkeypatch.setenv("SMTP_TIMEOUT_SECONDS", "12")

    from app.services import email_service as mod

    monkeypatch.setattr(mod, "_email_service", None)

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port
            self.timeout = timeout
            self.logged_in = False
            FakeSMTP.last = self

        def login(self, user, password):
            self.logged_in = True

        def sendmail(self, frm, to, msg):
            self.sent = (frm, to, msg)

        def quit(self):
            self.quit_called = True

        def close(self):
            self.closed = True

    monkeypatch.setattr(mod.smtplib, "SMTP_SSL", FakeSMTP)
    svc = mod.get_email_service()
    ok, msg = svc.send_email("to@example.com", "Hello", "<b>x</b>")
    assert ok is True
    assert msg == "sent"
    assert FakeSMTP.last.timeout == 12
    assert FakeSMTP.last.logged_in is True
