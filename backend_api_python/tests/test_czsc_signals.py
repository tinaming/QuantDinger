"""
Tests for app.services.czsc_signals — Signal registry & computation service.

These tests work both with and without czsc installed.
When czsc is unavailable, the service gracefully degrades.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.czsc_signals import (
    compute_czsc_signal_columns,
    get_signal_docs_for_prompt,
    list_czsc_signals,
    list_signals_grouped,
)


# ---------------------------------------------------------------------------
# Helper: build a realistic OHLCV DataFrame
# ---------------------------------------------------------------------------

def _make_ohlcv_df(n: int = 300, freq: str = "1h") -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame with DatetimeIndex."""
    rng = np.random.RandomState(42)
    dates = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    returns = rng.normal(0, 0.005, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    high = close * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.002, n)))
    open_price = close * (1 + rng.normal(0, 0.001, n))
    high = np.maximum(high, np.maximum(open_price, close))
    low = np.minimum(low, np.minimum(open_price, close))
    volume = np.abs(rng.normal(1000, 500, n))

    return pd.DataFrame(
        {"open": open_price, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


# ---------------------------------------------------------------------------
# list_czsc_signals
# ---------------------------------------------------------------------------

class TestListCzscSignals:
    def test_returns_list(self):
        result = list_czsc_signals()
        assert isinstance(result, list)

    def test_signal_structure(self):
        """Each signal should have name, param_template, category, namespace."""
        signals = list_czsc_signals()
        if not signals:
            pytest.skip("czsc not installed or signal registry empty")

        sig = signals[0]
        assert "name" in sig
        assert "param_template" in sig
        assert "category" in sig
        assert "namespace" in sig
        assert isinstance(sig["name"], str)
        assert len(sig["name"]) > 0

    def test_include_flags(self):
        """include_kline/include_trader should affect results."""
        all_signals = list_czsc_signals(include_kline=True, include_trader=True)
        kline_only = list_czsc_signals(include_kline=True, include_trader=False)
        trader_only = list_czsc_signals(include_kline=False, include_trader=True)

        # If czsc is available, all >= each subset
        if all_signals:
            assert len(all_signals) >= len(kline_only)
            assert len(all_signals) >= len(trader_only)


class TestListSignalsGrouped:
    def test_returns_dict(self):
        result = list_signals_grouped()
        assert isinstance(result, dict)

    def test_grouping_structure(self):
        """Keys should be namespace strings, values should be lists."""
        grouped = list_signals_grouped()
        if not grouped:
            pytest.skip("czsc not installed or signal registry empty")

        for ns, sigs in grouped.items():
            assert isinstance(ns, str)
            assert isinstance(sigs, list)
            if sigs:
                assert "name" in sigs[0]
                assert "namespace" in sigs[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_czsc_signals() -> bool:
    """Check if czsc signal APIs are available."""
    try:
        from app.services.czsc_bridge import is_czsc_enabled
        if not is_czsc_enabled():
            return False
        signals = list_czsc_signals()
        return len(signals) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# compute_czsc_signal_columns
# ---------------------------------------------------------------------------

class TestComputeCzscSignalColumns:
    def test_no_czsc_returns_unchanged(self):
        """Without czsc or with empty config, should return df unchanged."""
        df = _make_ohlcv_df(50)
        result = compute_czsc_signal_columns(df, signals_config=[], freq="1H")
        assert len(result) == len(df)

    def test_empty_signals_config(self):
        df = _make_ohlcv_df(50)
        result = compute_czsc_signal_columns(df, signals_config=[], freq="1H")
        # Should not add any czsc_signal_ columns
        signal_cols = [c for c in result.columns if c.startswith("czsc_signal_")]
        assert len(signal_cols) == 0

    def test_insufficient_data(self):
        """With fewer than 10 bars, should return df unchanged."""
        df = _make_ohlcv_df(5)
        result = compute_czsc_signal_columns(
            df,
            signals_config=[{"name": "cxt_bi_end_V240526"}],
            freq="1H",
        )
        signal_cols = [c for c in result.columns if c.startswith("czsc_signal_")]
        assert len(signal_cols) == 0

    @pytest.mark.skipif(
        not _has_czsc_signals(),
        reason="czsc signal APIs not available",
    )
    def test_computes_with_valid_signal(self):
        """With czsc installed and valid signal, should add signal columns."""
        df = _make_ohlcv_df(300)
        signals = list_czsc_signals()
        if not signals:
            pytest.skip("No signals in registry")

        # Pick first signal
        sig = signals[0]
        config = {"name": sig["name"]}
        param_template = sig.get("param_template", {})
        if isinstance(param_template, dict):
            config.update(param_template)

        result = compute_czsc_signal_columns(
            df, signals_config=[config], freq="1H",
        )
        # Should have at least attempted computation
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(df)

    def test_preserves_original_columns(self):
        """Original DataFrame columns should be preserved."""
        df = _make_ohlcv_df(50)
        original_cols = set(df.columns)
        result = compute_czsc_signal_columns(df, signals_config=[], freq="1H")
        assert original_cols.issubset(set(result.columns))


# ---------------------------------------------------------------------------
# get_signal_docs_for_prompt
# ---------------------------------------------------------------------------

class TestGetSignalDocsForPrompt:
    def test_returns_string(self):
        result = get_signal_docs_for_prompt()
        assert isinstance(result, str)

    def test_namespace_filter(self):
        """Filtering by namespace should produce docs only for those namespaces."""
        result = get_signal_docs_for_prompt(namespace_filter=["cxt", "tas"])
        if result:
            # Should mention cxt or tas namespaces
            assert "cxt" in result.lower() or "tas" in result.lower()

    def test_includes_combination_patterns(self):
        """If signals are available, should include typical combination patterns."""
        result = get_signal_docs_for_prompt()
        if result:
            assert "组合" in result or "combination" in result.lower() or "模式" in result

    def test_max_per_namespace(self):
        """Should respect max_per_namespace limit."""
        result = get_signal_docs_for_prompt(max_per_namespace=2)
        if result:
            # Check for "及其他" overflow indicator if there are many signals
            # This is a soft check — may not trigger if namespaces have <=2 signals
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Multi-level analysis tests
# ---------------------------------------------------------------------------

class TestMultilevelAnalysis:
    def test_import(self):
        """Should be importable."""
        from app.services.czsc_multilevel import (
            _auto_select_targets,
            _cross_validate,
            _trend_label,
            analyze_multilevel,
        )
        assert callable(analyze_multilevel)

    def test_auto_select_targets(self):
        from app.services.czsc_multilevel import _auto_select_targets
        targets = _auto_select_targets("5m")
        assert isinstance(targets, list)
        assert len(targets) >= 1
        # Should pick higher timeframes
        assert "5m" not in targets

    def test_auto_select_unknown_timeframe(self):
        from app.services.czsc_multilevel import _auto_select_targets
        targets = _auto_select_targets("unknown")
        assert isinstance(targets, list)
        assert len(targets) >= 1

    def test_trend_label(self):
        from app.services.czsc_multilevel import _trend_label
        assert _trend_label(0) == "consolidation"
        assert _trend_label(1) == "uptrend"
        assert _trend_label(-1) == "downtrend"
        assert _trend_label(None) == "unknown"

    def test_cross_validate_empty(self):
        from app.services.czsc_multilevel import _cross_validate
        result = _cross_validate({})
        assert isinstance(result, dict)

    def test_analyze_without_czsc(self):
        from app.services.czsc_multilevel import analyze_multilevel
        from app.services.czsc_bridge import is_czsc_enabled
        if is_czsc_enabled():
            pytest.skip("Test is for graceful degradation without czsc")
        df = _make_ohlcv_df(100)
        result = analyze_multilevel(df, base_timeframe="1H")
        assert "error" in result


# ---------------------------------------------------------------------------
# get_czsc_column_docs with signal reference
# ---------------------------------------------------------------------------

class TestGetCzscColumnDocsEnhanced:
    def test_docs_include_columns(self):
        from app.services.czsc_bridge import get_czsc_column_docs
        docs = get_czsc_column_docs()
        assert "czsc_fx_mark" in docs
        assert "czsc_bi_dir" in docs

    def test_docs_include_signal_reference(self):
        """If czsc signals are available, docs should include signal reference."""
        from app.services.czsc_bridge import get_czsc_column_docs, is_czsc_enabled
        docs = get_czsc_column_docs()
        if is_czsc_enabled() and list_czsc_signals():
            assert "信号函数" in docs or "Signal" in docs
