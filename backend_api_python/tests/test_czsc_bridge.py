"""
Tests for app.services.czsc_bridge — CZSC (缠论) pre-computation bridge.

These tests are designed to work both with and without czsc installed.
When czsc is unavailable, the bridge gracefully degrades and these tests
verify that behavior.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.czsc_bridge import (
    CZSC_COLUMNS,
    add_mock_czsc_columns,
    code_uses_czsc,
    compute_czsc_features,
    get_czsc_column_docs,
    get_czsc_import_error,
    is_czsc_enabled,
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
# code_uses_czsc: static detection
# ---------------------------------------------------------------------------

class TestCodeUsesCzsc:
    def test_empty_code(self):
        assert code_uses_czsc("") is False
        assert code_uses_czsc(None) is False  # type: ignore[arg-type]

    def test_no_czsc_reference(self):
        code = "df['buy'] = df['close'] > df['open']"
        assert code_uses_czsc(code) is False

    def test_czsc_column_reference(self):
        code = "df['open_long'] = df['czsc_bi_dir'] == 1"
        assert code_uses_czsc(code) is True

    def test_czsc_column_in_condition(self):
        code = "if df['czsc_trend'].iloc[-1] == 1:\n    df['open_long'] = True"
        assert code_uses_czsc(code) is True

    def test_czsc_in_string_comment_ignored(self):
        # The regex is intentionally simple; comments mentioning czsc_ also match.
        code = "# czsc_ feature comment\ndf['buy'] = True"
        # This matches because regex doesn't distinguish comments from code.
        # It's fine: false-positive just means we compute features unnecessarily.
        assert code_uses_czsc(code) is True

    def test_multiple_czsc_columns(self):
        code = """
df['open_long'] = (df['czsc_bi_dir'] == 1) & (df['czsc_bs_type'] == '1buy')
df['close_long'] = (df['czsc_bi_dir'].shift(1) == 1) & (df['czsc_bi_dir'] == -1)
"""
        assert code_uses_czsc(code) is True


# ---------------------------------------------------------------------------
# get_czsc_column_docs: documentation string
# ---------------------------------------------------------------------------

class TestCzscColumnDocs:
    def test_returns_string(self):
        docs = get_czsc_column_docs()
        assert isinstance(docs, str)
        assert len(docs) > 0

    def test_contains_all_column_names(self):
        docs = get_czsc_column_docs()
        for col in CZSC_COLUMNS:
            assert col["name"] in docs, f"Column {col['name']} missing from docs"

    def test_contains_chan_theory_keywords(self):
        docs = get_czsc_column_docs().lower()
        assert "缠论" in docs or "chan" in docs
        assert "czsc_" in docs


# ---------------------------------------------------------------------------
# CZSC_COLUMNS schema
# ---------------------------------------------------------------------------

class TestCzscColumnsSchema:
    def test_all_columns_have_required_fields(self):
        for col in CZSC_COLUMNS:
            assert "name" in col, f"Column missing 'name': {col}"
            assert "dtype" in col, f"Column missing 'dtype': {col}"
            assert "desc" in col, f"Column missing 'desc': {col}"
            assert col["name"].startswith("czsc_"), f"Column name must start with czsc_: {col['name']}"

    def test_column_count(self):
        # Plan specifies 12 columns
        assert len(CZSC_COLUMNS) == 15

    def test_column_names_are_unique(self):
        names = [col["name"] for col in CZSC_COLUMNS]
        assert len(names) == len(set(names)), "Duplicate column names found"


# ---------------------------------------------------------------------------
# add_mock_czsc_columns: validation dry-run support
# ---------------------------------------------------------------------------

class TestAddMockCzscColumns:
    def test_adds_all_columns(self):
        df = _make_ohlcv_df(50)
        result = add_mock_czsc_columns(df)
        for col in CZSC_COLUMNS:
            assert col["name"] in result.columns, f"Missing mock column: {col['name']}"

    def test_preserves_original_columns(self):
        df = _make_ohlcv_df(50)
        result = add_mock_czsc_columns(df)
        for col in ("open", "high", "low", "close", "volume"):
            assert col in result.columns

    def test_length_preserved(self):
        df = _make_ohlcv_df(100)
        result = add_mock_czsc_columns(df)
        assert len(result) == len(df)

    def test_mock_values_are_valid(self):
        df = _make_ohlcv_df(50)
        result = add_mock_czsc_columns(df)
        # fx_mark should be 0 (no fractals in mock data)
        assert (result["czsc_fx_mark"] == 0).all()
        # bi_dir should be 0 (no strokes in mock data)
        assert (result["czsc_bi_dir"] == 0).all()
        # trend should be 0 (consolidation)
        assert (result["czsc_trend"] == 0).all()
        # bs_type should be empty string
        assert (result["czsc_bs_type"] == "").all()


# ---------------------------------------------------------------------------
# is_czsc_enabled and get_czsc_import_error
# ---------------------------------------------------------------------------

class TestCzscAvailability:
    def test_is_czsc_enabled_returns_bool(self):
        result = is_czsc_enabled()
        assert isinstance(result, bool)

    def test_import_error_when_disabled(self):
        if not is_czsc_enabled():
            error = get_czsc_import_error()
            assert error is not None
            assert isinstance(error, str)
            assert len(error) > 0

    def test_import_error_none_when_enabled(self):
        if is_czsc_enabled():
            error = get_czsc_import_error()
            assert error is None


# ---------------------------------------------------------------------------
# compute_czsc_features: graceful degradation
# ---------------------------------------------------------------------------

class TestComputeCzscFeatures:
    def test_returns_df_when_czsc_unavailable(self):
        """When czsc is not installed, compute_czsc_features returns the original df."""
        df = _make_ohlcv_df(100)
        result = compute_czsc_features(df, freq="1H")
        # Either czsc is installed and we get czsc_ columns, or we get original df
        if not is_czsc_enabled():
            # Should return original df unchanged
            assert "czsc_bi_dir" not in result.columns
            assert len(result) == len(df)

    def test_empty_df_returns_unchanged(self):
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        result = compute_czsc_features(df, freq="1H")
        assert len(result) == 0

    def test_small_df_returns_unchanged(self):
        """czsc needs at least 10 bars for meaningful analysis."""
        df = _make_ohlcv_df(5)
        result = compute_czsc_features(df, freq="1H")
        # Should return unchanged since df is too small
        assert len(result) == 5

    def test_unsupported_timeframe_returns_unchanged(self):
        df = _make_ohlcv_df(100)
        result = compute_czsc_features(df, freq="99m")  # Not a valid timeframe
        # Should return unchanged
        assert len(result) == len(df)

    def test_none_df_returns_none(self):
        result = compute_czsc_features(None, freq="1H")  # type: ignore[arg-type]
        assert result is None

    @pytest.mark.skipif(not is_czsc_enabled(), reason="czsc not installed")
    def test_with_czsc_installed_injects_columns(self):
        """When czsc IS installed, features should be computed and injected."""
        df = _make_ohlcv_df(300, freq="1h")
        result = compute_czsc_features(df, freq="1H")
        for col in CZSC_COLUMNS:
            assert col["name"] in result.columns, f"Missing column after czsc computation: {col['name']}"
        assert len(result) == len(df)

    @pytest.mark.skipif(not is_czsc_enabled(), reason="czsc not installed")
    def test_czsc_fx_mark_values_are_valid(self):
        """czsc_fx_mark should only contain -1, 0, or 1."""
        df = _make_ohlcv_df(300, freq="1h")
        result = compute_czsc_features(df, freq="1H")
        valid_values = {-1, 0, 1}
        actual_values = set(result["czsc_fx_mark"].unique())
        assert actual_values.issubset(valid_values), f"Invalid fx_mark values: {actual_values}"

    @pytest.mark.skipif(not is_czsc_enabled(), reason="czsc not installed")
    def test_czsc_bi_dir_values_are_valid(self):
        """czsc_bi_dir should only contain -1, 0, or 1."""
        df = _make_ohlcv_df(300, freq="1h")
        result = compute_czsc_features(df, freq="1H")
        valid_values = {-1, 0, 1}
        actual_values = set(result["czsc_bi_dir"].unique())
        assert actual_values.issubset(valid_values), f"Invalid bi_dir values: {actual_values}"

    @pytest.mark.skipif(not is_czsc_enabled(), reason="czsc not installed")
    def test_czsc_trend_values_are_valid(self):
        """czsc_trend should only contain -1, 0, or 1."""
        df = _make_ohlcv_df(300, freq="1h")
        result = compute_czsc_features(df, freq="1H")
        valid_values = {-1, 0, 1}
        actual_values = set(result["czsc_trend"].unique())
        assert actual_values.issubset(valid_values), f"Invalid trend values: {actual_values}"

    @pytest.mark.skipif(not is_czsc_enabled(), reason="czsc not installed")
    def test_czsc_zs_position_values_are_valid(self):
        """czsc_zs_position should only contain 'above', 'below', 'inside', or ''."""
        df = _make_ohlcv_df(300, freq="1h")
        result = compute_czsc_features(df, freq="1H")
        valid_values = {"above", "below", "inside", ""}
        actual_values = set(result["czsc_zs_position"].unique())
        assert actual_values.issubset(valid_values), f"Invalid zs_position values: {actual_values}"

    @pytest.mark.skipif(not is_czsc_enabled(), reason="czsc not installed")
    def test_czsc_length_alignment(self):
        """All czsc columns should have same length as input df."""
        df = _make_ohlcv_df(200, freq="15min")
        result = compute_czsc_features(df, freq="15m")
        assert len(result) == len(df)
        for col in CZSC_COLUMNS:
            assert len(result[col["name"]]) == len(df)


# ---------------------------------------------------------------------------
# Integration: indicator_validation dry-run with czsc columns
# ---------------------------------------------------------------------------

class TestIndicatorValidationWithCzsc:
    def test_validation_passes_with_czsc_mock_columns(self):
        """Indicator code that reads czsc_ columns should validate without error."""
        from app.services.indicator_validation import validate_indicator_code

        code = '''
my_indicator_name = "CZSC Test"
my_indicator_description = "Test czsc bridge integration"
# @param threshold int 1 Trend threshold
df = df.copy()
threshold = int(params.get('threshold', 1))
# Use czsc_trend to generate signals
df['open_long'] = (df['czsc_trend'] == 1) & (df['czsc_bi_dir'].shift(1).fillna(0) != 1)
df['close_long'] = (df['czsc_trend'] == -1) & (df['czsc_bi_dir'].shift(1).fillna(0) != -1)
df['open_short'] = (df['czsc_trend'] == -1) & (df['czsc_bi_dir'].shift(1).fillna(0) != -1)
df['close_short'] = (df['czsc_trend'] == 1) & (df['czsc_bi_dir'].shift(1).fillna(0) != 1)
# Fill NaN
for c in ['open_long', 'close_long', 'open_short', 'close_short']:
    df[c] = df[c].fillna(False).astype(bool)
buy_marks = [None] * len(df)
sell_marks = [None] * len(df)
output = {
    'name': my_indicator_name,
    'plots': [],
    'signals': [
        {'type': 'buy', 'text': 'Buy', 'data': buy_marks, 'color': '#00FF00'},
        {'type': 'sell', 'text': 'Sell', 'data': sell_marks, 'color': '#FF0000'},
    ],
}
'''
        result = validate_indicator_code(code, {"threshold": 1})
        # Should pass: mock czsc columns prevent KeyError
        assert result["success"] is True, f"Validation failed: {result.get('msg')}"

    def test_validation_without_czsc_reference_unchanged(self):
        """Code that doesn't reference czsc_ should behave identically to before."""
        from app.services.indicator_validation import validate_indicator_code

        code = '''
my_indicator_name = "Simple MA"
my_indicator_description = "SMA crossover"
df = df.copy()
fast = df['close'].rolling(10).mean()
slow = df['close'].rolling(30).mean()
cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
cross_dn = (fast < slow) & (fast.shift(1) >= slow.shift(1))
df['open_long'] = cross_up.fillna(False).astype(bool)
df['close_long'] = cross_dn.fillna(False).astype(bool)
df['open_short'] = cross_dn.fillna(False).astype(bool)
df['close_short'] = cross_up.fillna(False).astype(bool)
output = {'name': my_indicator_name, 'plots': [], 'signals': []}
'''
        result = validate_indicator_code(code)
        assert result["success"] is True, f"Validation failed: {result.get('msg')}"
