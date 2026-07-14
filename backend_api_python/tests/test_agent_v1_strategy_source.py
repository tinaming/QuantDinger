"""Tests for strategy list/get Agent Gateway endpoints — indicator fields.

Covers:
  - list_strategies projection includes indicator_name
  - get_strategy returns full indicator_config

StrategyService is mocked so no database is required.
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


def _auth_ok(monkeypatch):
    agent_auth._schema_ready = True
    monkeypatch.setattr(agent_auth, "_lookup_token",
                        lambda raw: _fake_token_row(scopes="R"))
    monkeypatch.setattr(agent_auth, "_touch_token_last_used", lambda *_: None)
    monkeypatch.setattr(agent_auth, "_audit", lambda *a, **kw: None)


STRATEGIES_MOD = "app.routes.agent_v1.strategies"

# A realistic strategy row with indicator_config embedded
_FAKE_STRATEGY_ROW = {
    "id": 42,
    "strategy_name": "MACD Crossover",
    "strategy_type": "IndicatorStrategy",
    "market_category": "CNStock",
    "symbol": "sh600519",
    "timeframe": "1D",
    "status": "stopped",
    "initial_capital": 10000,
    "leverage": 1,
    "market_type": "spot",
    "strategy_mode": "indicator",
    "execution_mode": "signal",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-06-01T00:00:00Z",
    "indicator_config": {
        "indicator_id": 7,
        "indicator_name": "MACD_V2",
        "indicator_code": "# indicator python source …",
        "params": {"fast": 12, "slow": 26, "signal": 9},
    },
    "trading_config": {
        "commission": 0.001,
        "slippage": 0.0001,
    },
}


def test_list_strategies_includes_indicator_name(client, monkeypatch):
    """list_strategies projection must surface indicator_name from indicator_config."""
    _auth_ok(monkeypatch)
    with patch(f"{STRATEGIES_MOD}._strategy_service") as mock_svc, \
         patch(f"{STRATEGIES_MOD}.current_user_id", return_value=1):
        mock_svc.list_strategies.return_value = [_FAKE_STRATEGY_ROW]

        resp = client.get("/api/agent/v1/strategies", headers=_bearer())

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == 0
    items = body["data"]
    assert isinstance(items, list) and len(items) == 1
    item = items[0]
    # indicator_name should be promoted to top-level
    assert item.get("indicator_name") == "MACD_V2"
    # strategy_name should also be present
    assert item.get("strategy_name") == "MACD Crossover"


def test_get_strategy_returns_indicator_config(client, monkeypatch):
    """get_strategy must include the full indicator_config block (secrets redacted)."""
    _auth_ok(monkeypatch)
    with patch(f"{STRATEGIES_MOD}._strategy_service") as mock_svc, \
         patch(f"{STRATEGIES_MOD}.current_user_id", return_value=1):
        mock_svc.get_strategy.return_value = _FAKE_STRATEGY_ROW

        resp = client.get("/api/agent/v1/strategies/42", headers=_bearer())

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == 0
    data = body["data"]
    assert data["id"] == 42
    # indicator_config must be present with its nested fields
    ic = data.get("indicator_config")
    assert ic is not None
    assert ic.get("indicator_name") == "MACD_V2"
    assert ic.get("indicator_id") == 7
    # indicator_name should also appear at top level
    assert data.get("indicator_name") == "MACD_V2"
