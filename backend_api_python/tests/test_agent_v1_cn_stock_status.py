"""Tests for CNStock data-source-status Agent Gateway endpoint.

Covers:
  - /api/agent/v1/markets/CNStock/data-source-status  (happy path)
  - Scope enforcement (requires R scope)

CNStockDataSource.get_data_source_status is mocked so no real data-source
probes are attempted.
"""
from __future__ import annotations

from unittest.mock import patch

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


def _auth_ok(monkeypatch, scopes: str = "R"):
    agent_auth._schema_ready = True
    monkeypatch.setattr(agent_auth, "_lookup_token",
                        lambda raw: _fake_token_row(scopes=scopes))
    monkeypatch.setattr(agent_auth, "_touch_token_last_used", lambda *_: None)
    monkeypatch.setattr(agent_auth, "_audit", lambda *a, **kw: None)


MARKETS_MOD = "app.routes.agent_v1.markets"

_FAKE_STATUS = {
    "market": "CNStock",
    "sources": [
        {"provider": "twelvedata", "enabled": True,  "tier": 1,
         "last_success_iso": "2024-06-01T00:00:00Z", "recent_error_count": 0},
        {"provider": "tencent",    "enabled": True,  "tier": 2,
         "last_success_iso": None,                   "recent_error_count": 0},
        {"provider": "yfinance",   "enabled": True,  "tier": 3,
         "last_success_iso": None,                   "recent_error_count": 1},
        {"provider": "akshare",    "enabled": False, "tier": 4,
         "last_success_iso": None,                   "recent_error_count": 3},
    ],
    "recent_error_count": 4,
}


def test_cn_stock_data_source_status(client, monkeypatch):
    """Endpoint should return the standard envelope with source list."""
    _auth_ok(monkeypatch)
    with patch(
        "app.data_sources.cn_stock.CNStockDataSource.get_data_source_status",
        return_value=_FAKE_STATUS,
    ):
        resp = client.get(
            "/api/agent/v1/markets/CNStock/data-source-status",
            headers=_bearer(),
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == 0
    data = body["data"]
    assert data["market"] == "CNStock"
    assert isinstance(data["sources"], list)
    assert len(data["sources"]) == 4
    providers = [s["provider"] for s in data["sources"]]
    assert "twelvedata" in providers
    assert "akshare" in providers


def test_cn_stock_data_source_status_requires_scope_r(client, monkeypatch):
    """A token without any scope must receive 403 (scope mismatch)."""
    # Give the token an empty scope set — R is required.
    agent_auth._schema_ready = True
    monkeypatch.setattr(agent_auth, "_lookup_token",
                        lambda raw: _fake_token_row(scopes=""))
    monkeypatch.setattr(agent_auth, "_touch_token_last_used", lambda *_: None)
    monkeypatch.setattr(agent_auth, "_audit", lambda *a, **kw: None)

    resp = client.get(
        "/api/agent/v1/markets/CNStock/data-source-status",
        headers=_bearer(),
    )
    # Empty scopes → no matching scope → 403
    assert resp.status_code == 403
