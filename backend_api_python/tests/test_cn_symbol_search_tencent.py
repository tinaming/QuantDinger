"""CNStock symbol search should prefer fast Tencent suggest over slow AkShare."""

from app.services.market import symbol_search as ss


def test_search_cn_tencent_parses_unicode_name(monkeypatch):
    class _Resp:
        status_code = 200
        text = 'v_hint="sh~601888~\\u4e2d\\u56fd\\u4e2d\\u514d~zgzm~GP-A"'

    def fake_get(*_a, **_k):
        return _Resp()

    monkeypatch.setattr(ss, "persist_seed_name", lambda *a, **k: None)
    import requests

    monkeypatch.setattr(requests, "get", fake_get)
    rows = ss._search_cn_tencent("601888", 5)
    assert rows
    assert rows[0]["market"] == "CNStock"
    assert rows[0]["symbol"] == "601888"
    assert "中免" in rows[0]["name"] or "中国中免" in rows[0]["name"]


def test_search_market_symbols_uses_tencent_before_akshare(monkeypatch):
    called = {"ak": 0}

    monkeypatch.setattr(
        ss,
        "seed_search_symbols",
        lambda **_k: [],
    )
    monkeypatch.setattr(
        ss,
        "_search_cn_tencent",
        lambda keyword, limit: [{"market": "CNStock", "symbol": "601888", "name": "中国中免"}],
    )

    def boom(*_a, **_k):
        called["ak"] += 1
        return []

    monkeypatch.setattr(ss, "_search_cn_akshare", boom)
    out = ss.search_market_symbols("CNStock", "601888", 5)
    assert out[0]["symbol"] == "601888"
    assert called["ak"] == 0
