"""Tests for CZSC (缠论) Agent Gateway endpoints.

Covers:
  - /api/agent/v1/czsc/status  (available + unavailable paths)
  - /api/agent/v1/czsc/analyze (not-installed + success paths)

All czsc_bridge dependencies are mocked so no real czsc library is needed.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from app.utils import agent_auth


@pytest.fixture(autouse=True)
def _reset_rate_limit_state():
    agent_auth._rate_state.clear()
    yield
    agent_auth._rate_state.clear()


def _fake_token_row(scopes: str = "R", paper_only: bool = True, status: str = "active",
                    expires_at=None, rate_limit_per_min: int = 60) -> dict:
    return {
        "id": 999,
        "user_id": 1,
        "name": "test-agent",
        "scopes": scopes,
        "markets": "*",
        "instruments": "*",
        "paper_only": paper_only,
        "rate_limit_per_min": rate_limit_per_min,
        "status": status,
        "expires_at": expires_at,
    }


def _bearer(token: str = "qd_agent_TESTTOKEN12345") -> dict:
    return {"Authorization": f"Bearer {token}"}


def _auth_ok(monkeypatch):
    """Install a valid R-scoped token so /czsc/* routes are reachable."""
    agent_auth._schema_ready = True
    monkeypatch.setattr(agent_auth, "_lookup_token",
                        lambda raw: _fake_token_row(scopes="R"))
    monkeypatch.setattr(agent_auth, "_touch_token_last_used", lambda *_: None)
    monkeypatch.setattr(agent_auth, "_audit", lambda *a, **kw: None)


CZSC_BRIDGE = "app.routes.agent_v1.czsc"


def test_czsc_status_unavailable(client, monkeypatch):
    """When czsc is not installed, czsc_available must be false."""
    _auth_ok(monkeypatch)
    with patch(f"{CZSC_BRIDGE}.is_czsc_enabled", return_value=False), \
         patch(f"{CZSC_BRIDGE}.get_czsc_import_error", return_value="No module named 'czsc'"):
        resp = client.get("/api/agent/v1/czsc/status", headers=_bearer())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == 0
    data = body["data"]
    assert data["czsc_available"] is False
    assert data["czsc_version"] is None
    assert "No module" in (data["import_error"] or "")


def test_czsc_status_available(client, monkeypatch):
    """When czsc is installed, czsc_available must be true with a version."""
    _auth_ok(monkeypatch)
    with patch(f"{CZSC_BRIDGE}.is_czsc_enabled", return_value=True):
        resp = client.get("/api/agent/v1/czsc/status", headers=_bearer())
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["czsc_available"] is True
    # czsc_version may be "unknown" if real czsc isn't importable in test env
    assert data["czsc_version"] is not None


def test_czsc_analyze_not_installed(client, monkeypatch):
    """Calling /czsc/analyze when czsc is unavailable returns 400 + install hint."""
    _auth_ok(monkeypatch)
    with patch(f"{CZSC_BRIDGE}.is_czsc_enabled", return_value=False), \
         patch(f"{CZSC_BRIDGE}.get_czsc_import_error", return_value="No module named 'czsc'"):
        resp = client.post(
            "/api/agent/v1/czsc/analyze",
            headers=_bearer(),
            content_type="application/json",
            json={"market": "CNStock", "symbol": "sh600519", "timeframe": "1D", "limit": 300},
        )
    assert resp.status_code == 400
    body = resp.get_json()
    assert "not installed" in body["message"].lower() or "install" in body["message"].lower()
    details = body.get("details") or {}
    assert details.get("install_command") == "pip install czsc"


def test_czsc_analyze_success(client, monkeypatch):
    """Happy path: czsc available + kline data → analysis result."""
    _auth_ok(monkeypatch)

    # Build a minimal DataFrame that looks like czsc output
    n = 20
    df_out = pd.DataFrame({
        "open": [1.0] * n,
        "high": [2.0] * n,
        "low": [0.5] * n,
        "close": [1.5] * n,
        "czsc_bi_dir": [1] * 10 + [-1] * 10,
        "czsc_zs_level": [0] * n,
        "czsc_bs_type": [""] * 18 + ["buy", "sell"],
    })

    kline_rows = [
        {"dt": f"2024-01-{i+1:02d}", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}
        for i in range(n)
    ]

    with patch(f"{CZSC_BRIDGE}.is_czsc_enabled", return_value=True), \
         patch(f"{CZSC_BRIDGE}.compute_czsc_features", return_value=df_out), \
         patch(f"{CZSC_BRIDGE}._kline_service") as mock_ks:
        mock_ks.get_kline.return_value = kline_rows
        resp = client.post(
            "/api/agent/v1/czsc/analyze",
            headers=_bearer(),
            content_type="application/json",
            json={"market": "CNStock", "symbol": "sh600519", "timeframe": "1D", "limit": 300},
        )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["symbol"] == "sh600519"
    assert data["bar_count"] == n
    assert "czsc_columns" in data
    assert "signals" in data
    # Should have extracted the buy/sell signals
    assert len(data["signals"]) >= 1
