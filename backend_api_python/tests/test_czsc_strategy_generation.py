"""
Tests for CZSC (缠论) strategy generation — indicator validation,
backtest injection, and live strategy detection.

Covers:
  1. Indicator code that uses czsc_ columns validates via dry-run.
  2. Backtest executor detects czsc_ references and injects features.
  3. Live trading executor detects czsc_ references and injects features.
  4. Strategy creation with embedded CZSC indicator code.
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
    is_czsc_enabled,
)


# ---------------------------------------------------------------------------
# CZSC Indicator Code — follows four-way execution contract
# ---------------------------------------------------------------------------

CZSC_TREND_INDICATOR_CODE = '''
# signal_form: four_way
# exit_owner: engine
# flip_mode: R2
# @strategy market crypto
# @strategy symbol BTCUSDT
# @strategy timeframe 1H
# @strategy tradeDirection both
# @param trend_filter int 1 Trend filter: 1=only trend direction, 0=allow all

my_indicator_name = "CZSC Trend Reversal"
my_indicator_description = "缠论趋势反转策略：基于笔方向翻转 + 买卖点 + 趋势过滤"

df = df.copy()
trend_filter = int(params.get('trend_filter', 1))

# ── Feature engineering from czsc_ columns ──
bi_dir = df['czsc_bi_dir']
bi_dir_prev = bi_dir.shift(1).fillna(0)
bs_type = df['czsc_bs_type'].fillna('')
trend = df['czsc_trend'].fillna(0)
zs_position = df['czsc_zs_position'].fillna('')

# ── Raw signal conditions ──
# Long entry: upward stroke begins (bi_dir flips from -1/0 to +1)
# AND either trend is up OR a buy point appeared
bi_flip_up = (bi_dir == 1) & (bi_dir_prev != 1)
has_buy_point = bs_type.str.contains('buy', case=False, na=False) & (bs_type != '')
long_cond = bi_flip_up & (has_buy_point | (trend >= 0))

# Short entry: downward stroke begins (bi_dir flips from 1/0 to -1)
# AND either trend is down OR a sell point appeared
bi_flip_dn = (bi_dir == -1) & (bi_dir_prev != -1)
has_sell_point = bs_type.str.contains('sell', case=False, na=False) & (bs_type != '')
short_cond = bi_flip_dn & (has_sell_point | (trend <= 0))

# Apply trend filter: only trade in the dominant trend direction
if trend_filter == 1:
    long_cond = long_cond & (trend >= 0)
    short_cond = short_cond & (trend <= 0)

# ── Edge extraction (first occurrence only) ──
def edge(s):
    s = s.fillna(False).astype(bool)
    prev = s.shift(1).fillna(False).astype(int)
    return s & (prev == 0)

long_edge = edge(long_cond)
short_edge = edge(short_cond)

# ── Four-way execution columns ──
# open_long: flip-up edge (closes short if any, opens long)
# close_long: flip-down edge (exits long)
# open_short: flip-down edge (closes long if any, opens short)
# close_short: flip-up edge (exits short)
df['open_long'] = long_edge
df['close_long'] = edge(bi_flip_dn)
df['open_short'] = short_edge
df['close_short'] = edge(bi_flip_up)

# ── Signal markers for chart ──
buy_marks = [
    float(df['low'].iloc[i]) * 0.995 if bool(df['open_long'].iloc[i]) else None
    for i in range(len(df))
]
sell_marks = [
    float(df['high'].iloc[i]) * 1.005 if bool(df['open_short'].iloc[i]) else None
    for i in range(len(df))
]

# ── Plots: stroke direction as background ──
bi_dir_list = bi_dir.tolist()
plots = [
    {
        'name': 'Bi Direction',
        'type': 'line',
        'data': bi_dir_list,
        'color': '#888888',
        'width': 1,
    }
]

output = {
    'name': my_indicator_name,
    'plots': plots,
    'signals': [
        {'type': 'buy', 'text': 'Buy', 'data': buy_marks, 'color': '#00FF00'},
        {'type': 'sell', 'text': 'Sell', 'data': sell_marks, 'color': '#FF0000'},
    ],
}
'''


CZSC_CENTER_BREAKOUT_CODE = '''
# signal_form: four_way
# exit_owner: engine
# flip_mode: R2
# @strategy market crypto
# @strategy symbol ETHUSDT
# @strategy timeframe 4H
# @strategy tradeDirection both
# @param min_level int 1 Minimum center level for breakout signals

my_indicator_name = "CZSC Center Breakout"
my_indicator_description = "缠论中枢突破策略：价格突破中枢上下沿 + 笔方向确认"

df = df.copy()
min_level = int(params.get('min_level', 1))

# ── Feature engineering ──
zs_level = df['czsc_zs_level'].fillna(0)
zs_zd = df['czsc_zs_zd'].fillna(0)
zs_zg = df['czsc_zs_zg'].fillna(0)
zs_pos = df['czsc_zs_position'].fillna('')
bi_dir = df['czsc_bi_dir'].fillna(0)
trend = df['czsc_trend'].fillna(0)

# ── Breakout conditions ──
has_center = zs_level >= min_level

# Long: price breaks above center top (zs_zg) with upward stroke
breakout_up = has_center & (zs_pos == 'above') & (bi_dir == 1)

# Short: price breaks below center bottom (zs_zd) with downward stroke
breakout_dn = has_center & (zs_pos == 'below') & (bi_dir == -1)

# ── Edge extraction ──
def edge(s):
    s = s.fillna(False).astype(bool)
    prev = s.shift(1).fillna(False).astype(int)
    return s & (prev == 0)

long_edge = edge(breakout_up)
short_edge = edge(breakout_dn)

# Exit: price returns inside center
exit_long = edge((zs_pos == 'inside') | (zs_pos == 'below'))
exit_short = edge((zs_pos == 'inside') | (zs_pos == 'above'))

# ── Four-way execution ──
df['open_long'] = long_edge
df['close_long'] = exit_long
df['open_short'] = short_edge
df['close_short'] = exit_short

# ── Markers ──
buy_marks = [
    float(df['low'].iloc[i]) * 0.998 if bool(df['open_long'].iloc[i]) else None
    for i in range(len(df))
]
sell_marks = [
    float(df['high'].iloc[i]) * 1.002 if bool(df['open_short'].iloc[i]) else None
    for i in range(len(df))
]

# ── Plots: center zones ──
zd_list = zs_zd.tolist()
zg_list = zs_zg.tolist()
plots = [
    {'name': 'ZD (Center Low)', 'type': 'line', 'data': zd_list, 'color': '#00AA00', 'width': 1},
    {'name': 'ZG (Center High)', 'type': 'line', 'data': zg_list, 'color': '#AA0000', 'width': 1},
]

output = {
    'name': my_indicator_name,
    'plots': plots,
    'signals': [
        {'type': 'buy', 'text': 'Breakout Up', 'data': buy_marks, 'color': '#00FF00'},
        {'type': 'sell', 'text': 'Breakout Down', 'data': sell_marks, 'color': '#FF0000'},
    ],
}
'''


# ---------------------------------------------------------------------------
# Helpers
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
# Test 1: code_uses_czsc detection for strategy code
# ---------------------------------------------------------------------------

class TestCzscStrategyCodeDetection:
    """Verify that czsc_ references in strategy code are detected."""

    def test_trend_indicator_detected_as_czsc(self):
        assert code_uses_czsc(CZSC_TREND_INDICATOR_CODE) is True

    def test_center_breakout_detected_as_czsc(self):
        assert code_uses_czsc(CZSC_CENTER_BREAKOUT_CODE) is True

    def test_plain_indicator_not_detected(self):
        plain = "df['open_long'] = df['close'] > df['open']"
        assert code_uses_czsc(plain) is False


# ---------------------------------------------------------------------------
# Test 2: Indicator validation with czsc_ columns (dry-run)
# ---------------------------------------------------------------------------

class TestCzscIndicatorValidation:
    """Validate CZSC indicator code through the dry-run pipeline.

    The validation sandbox injects mock czsc_ columns (via add_mock_czsc_columns)
    so indicator code that reads czsc_ columns doesn't get KeyError.
    """

    def test_trend_indicator_validates(self):
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_TREND_INDICATOR_CODE, {"trend_filter": 1})
        assert result["success"] is True, (
            f"Trend indicator validation failed: {result.get('msg')} | {result.get('details')}"
        )

    def test_center_breakout_validates(self):
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_CENTER_BREAKOUT_CODE, {"min_level": 1})
        assert result["success"] is True, (
            f"Center breakout validation failed: {result.get('msg')} | {result.get('details')}"
        )

    def test_trend_indicator_has_signals(self):
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_TREND_INDICATOR_CODE, {"trend_filter": 1})
        assert result["success"] is True
        assert result.get("signals_count", 0) >= 2, "Expected at least 2 signal definitions"

    def test_center_breakout_has_plots(self):
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_CENTER_BREAKOUT_CODE, {"min_level": 1})
        assert result["success"] is True
        assert result.get("plots_count", 0) >= 2, "Expected at least 2 plot definitions"

    def test_validation_without_params_uses_defaults(self):
        """Both indicators declare @param with defaults; validate without params should work."""
        from app.services.indicator_validation import validate_indicator_code
        r1 = validate_indicator_code(CZSC_TREND_INDICATOR_CODE)
        assert r1["success"] is True, f"Default param validation failed: {r1.get('msg')}"
        r2 = validate_indicator_code(CZSC_CENTER_BREAKOUT_CODE)
        assert r2["success"] is True, f"Default param validation failed: {r2.get('msg')}"


# ---------------------------------------------------------------------------
# Test 3: Backtest CZSC injection detection
# ---------------------------------------------------------------------------

class TestBacktestCzscInjection:
    """Verify that the backtest executor detects czsc_ references and
    calls compute_czsc_features (or gracefully skips if czsc unavailable)."""

    def test_backtest_detects_czsc_code(self):
        """code_uses_czsc returns True for our strategy code."""
        assert code_uses_czsc(CZSC_TREND_INDICATOR_CODE) is True
        assert code_uses_czsc(CZSC_CENTER_BREAKOUT_CODE) is True

    def test_compute_czsc_features_graceful_when_unavailable(self):
        """When czsc is not installed, compute_czsc_features returns df unchanged."""
        df = _make_ohlcv_df(200)
        result = compute_czsc_features(df, freq="1H", symbol="BTCUSDT")
        if not is_czsc_enabled():
            # Should return df without czsc_ columns
            assert "czsc_bi_dir" not in result.columns
            assert len(result) == len(df)
        else:
            # czsc IS installed; features should be injected
            assert "czsc_bi_dir" in result.columns
            assert len(result) == len(df)

    def test_mock_czsc_columns_sufficient_for_execution(self):
        """Mock czsc columns should let indicator code run without KeyError."""
        df = _make_ohlcv_df(200)
        df_mock = add_mock_czsc_columns(df)

        # Execute trend indicator code with mock columns
        exec_globals = {
            "df": df_mock.copy(),
            "pd": pd,
            "np": np,
            "params": {"trend_filter": 1},
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_TREND_INDICATOR_CODE, exec_globals)
        output = exec_globals.get("output")
        assert output is not None
        assert "name" in output
        assert output["name"] == "CZSC Trend Reversal"

    def test_mock_czsc_columns_sufficient_for_center_breakout(self):
        """Mock czsc columns should let center breakout code run."""
        df = _make_ohlcv_df(200)
        df_mock = add_mock_czsc_columns(df)

        exec_globals = {
            "df": df_mock.copy(),
            "pd": pd,
            "np": np,
            "params": {"min_level": 1},
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_CENTER_BREAKOUT_CODE, exec_globals)
        output = exec_globals.get("output")
        assert output is not None
        assert output["name"] == "CZSC Center Breakout"

    def test_four_way_columns_produced(self):
        """After executing CZSC indicator code, four-way columns should exist."""
        df = _make_ohlcv_df(200)
        df_mock = add_mock_czsc_columns(df)

        exec_globals = {
            "df": df_mock.copy(),
            "pd": pd,
            "np": np,
            "params": {"trend_filter": 1},
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_TREND_INDICATOR_CODE, exec_globals)
        result_df = exec_globals["df"]
        for col in ("open_long", "close_long", "open_short", "close_short"):
            assert col in result_df.columns, f"Missing four-way column: {col}"
            assert result_df[col].dtype == bool, f"Column {col} should be bool, got {result_df[col].dtype}"


# ---------------------------------------------------------------------------
# Test 4: Live strategy CZSC detection
# ---------------------------------------------------------------------------

class TestLiveStrategyCzscDetection:
    """Verify that the live trading executor would detect czsc_ references.

    We don't start a full executor; we test the detection logic that gates
    CZSC feature injection in trading_executor.py.
    """

    def test_trading_executor_would_detect_trend_code(self):
        """The code_uses_czsc check used by trading_executor.py should return True."""
        assert code_uses_czsc(CZSC_TREND_INDICATOR_CODE) is True

    def test_trading_executor_would_detect_breakout_code(self):
        assert code_uses_czsc(CZSC_CENTER_BREAKOUT_CODE) is True

    def test_non_czsc_code_not_triggered(self):
        """Plain indicator code should not trigger CZSC injection."""
        plain_code = "df['open_long'] = (df['close'] > df['open']).fillna(False).astype(bool)"
        assert code_uses_czsc(plain_code) is False


# ---------------------------------------------------------------------------
# Test 5: CZSC features computation with real czsc (conditional)
# ---------------------------------------------------------------------------

class TestCzscFeaturesComputation:
    """Test actual CZSC feature computation when the library is available."""

    @pytest.mark.skipif(not is_czsc_enabled(), reason="czsc not installed")
    def test_trend_indicator_with_real_czsc_features(self):
        """Run trend indicator with real czsc features injected."""
        df = _make_ohlcv_df(300, freq="1h")
        df_czsc = compute_czsc_features(df, freq="1H", symbol="BTCUSDT")

        # All czsc columns should exist
        for col in CZSC_COLUMNS:
            assert col["name"] in df_czsc.columns, f"Missing: {col['name']}"

        # Execute indicator code with real features
        exec_globals = {
            "df": df_czsc.copy(),
            "pd": pd,
            "np": np,
            "params": {"trend_filter": 1},
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_TREND_INDICATOR_CODE, exec_globals)
        output = exec_globals.get("output")
        assert output is not None
        assert output["name"] == "CZSC Trend Reversal"
        assert len(output.get("signals", [])) >= 2

    @pytest.mark.skipif(not is_czsc_enabled(), reason="czsc not installed")
    def test_center_breakout_with_real_czsc_features(self):
        """Run center breakout indicator with real czsc features."""
        df = _make_ohlcv_df(300, freq="1h")
        df_czsc = compute_czsc_features(df, freq="1H", symbol="ETHUSDT")

        exec_globals = {
            "df": df_czsc.copy(),
            "pd": pd,
            "np": np,
            "params": {"min_level": 1},
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_CENTER_BREAKOUT_CODE, exec_globals)
        output = exec_globals.get("output")
        assert output is not None
        assert output["name"] == "CZSC Center Breakout"

    def test_graceful_degradation_without_czsc(self):
        """Without czsc library, code should still validate (via mock columns)."""
        from app.services.indicator_validation import validate_indicator_code
        result = validate_indicator_code(CZSC_TREND_INDICATOR_CODE)
        assert result["success"] is True, (
            f"Graceful degradation failed: {result.get('msg')} | {result.get('details')}"
        )


# ---------------------------------------------------------------------------
# Test 6: End-to-end indicator authoring contract compliance
# ---------------------------------------------------------------------------

class TestCzscIndicatorContract:
    """Verify CZSC indicator code follows the platform authoring contract."""

    def test_has_indicator_name(self):
        assert 'my_indicator_name = ' in CZSC_TREND_INDICATOR_CODE
        assert 'my_indicator_name = ' in CZSC_CENTER_BREAKOUT_CODE

    def test_has_indicator_description(self):
        assert 'my_indicator_description = ' in CZSC_TREND_INDICATOR_CODE
        assert 'my_indicator_description = ' in CZSC_CENTER_BREAKOUT_CODE

    def test_has_four_way_signal_header(self):
        assert '# signal_form: four_way' in CZSC_TREND_INDICATOR_CODE
        assert '# signal_form: four_way' in CZSC_CENTER_BREAKOUT_CODE

    def test_has_strategy_headers(self):
        for code in (CZSC_TREND_INDICATOR_CODE, CZSC_CENTER_BREAKOUT_CODE):
            assert '# @strategy market' in code
            assert '# @strategy symbol' in code
            assert '# @strategy timeframe' in code
            assert '# @strategy tradeDirection' in code

    def test_has_output_variable(self):
        assert 'output = {' in CZSC_TREND_INDICATOR_CODE
        assert 'output = {' in CZSC_CENTER_BREAKOUT_CODE

    def test_uses_params_get(self):
        assert "params.get(" in CZSC_TREND_INDICATOR_CODE
        assert "params.get(" in CZSC_CENTER_BREAKOUT_CODE

    def test_declares_param_annotations(self):
        assert '# @param' in CZSC_TREND_INDICATOR_CODE
        assert '# @param' in CZSC_CENTER_BREAKOUT_CODE

    def test_does_not_import_czsc(self):
        """Indicator code must NOT import czsc; the bridge injects columns."""
        assert 'import czsc' not in CZSC_TREND_INDICATOR_CODE
        assert 'import czsc' not in CZSC_CENTER_BREAKOUT_CODE

    def test_signal_data_length_matches_df(self):
        """Signal marker lists should have exactly len(df) elements."""
        df = _make_ohlcv_df(200)
        df_mock = add_mock_czsc_columns(df)
        exec_globals = {
            "df": df_mock.copy(),
            "pd": pd,
            "np": np,
            "params": {"trend_filter": 1},
            "output": None,
        }
        for col in ("open", "high", "low", "close", "volume"):
            exec_globals[col] = exec_globals["df"][col]

        exec(CZSC_TREND_INDICATOR_CODE, exec_globals)
        output = exec_globals["output"]
        for sig in output.get("signals", []):
            assert len(sig["data"]) == len(df_mock), (
                f"Signal '{sig.get('text')}' data length {len(sig['data'])} != df length {len(df_mock)}"
            )
