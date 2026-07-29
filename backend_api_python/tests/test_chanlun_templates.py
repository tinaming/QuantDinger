"""
Tests for ChanLun official strategy templates (chanlun_templates).

Covers registry load, execution-contract headers, and dry-run of
true_3buy_mvp (leave-ZG pullback confirm — not bs_type / first-above).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.chanlun_templates import get_template, list_templates
from app.services.czsc_bridge import add_mock_czsc_columns, code_uses_czsc


TRUE_3BUY_ID = "true_3buy_mvp"
EXPECTED_TEMPLATE_IDS = {
    "fx_breakout",
    "zs_oscillation",
    "bsp_trend",
    "multi_level_resonance",
    "true_3buy_mvp",
}


def _make_ohlcv_df(n: int = 120) -> pd.DataFrame:
    rng = np.random.RandomState(7)
    dates = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = 100.0 + np.cumsum(rng.normal(0, 0.3, n))
    high = close + 0.5
    low = close - 0.5
    open_ = close.copy()
    volume = rng.uniform(800, 2000, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _exec_template(code: str, df: pd.DataFrame, params: dict | None = None):
    g = {
        "df": df.copy(),
        "pd": pd,
        "np": np,
        "params": params or {},
        "output": None,
    }
    for col in ("open", "high", "low", "close", "volume"):
        g[col] = g["df"][col]
    exec(code, g)
    return g["df"], g.get("output")


class TestChanlunTemplateRegistry:
    def test_list_includes_true_3buy_mvp(self):
        ids = {t["id"] for t in list_templates()}
        assert EXPECTED_TEMPLATE_IDS <= ids

    def test_get_true_3buy_mvp(self):
        tpl = get_template(TRUE_3BUY_ID)
        assert tpl is not None
        assert tpl["id"] == TRUE_3BUY_ID
        assert "真三买" in tpl["name"]
        assert "open_long" in tpl["code"]
        assert "exit_owner: engine" in tpl["code"]

    def test_unknown_template_returns_none(self):
        assert get_template("not_a_real_template") is None


class TestTrue3BuyMvpContract:
    @pytest.fixture
    def code(self) -> str:
        return get_template(TRUE_3BUY_ID)["code"]

    def test_four_way_and_edge_headers(self, code: str):
        assert "# signal_form: four_way" in code
        assert "# exit_owner: engine" in code
        assert "# signal_mode: confirmed" in code
        assert "# exit_signal_mode: confirmed" in code
        assert "trailingEnabled false" in code
        assert "def edge(" in code
        assert "import czsc" not in code

    def test_not_naive_3buy_aliases(self, code: str):
        """Entry must be leave→pullback state machine, not bs_type / sticky above."""
        assert "leave_above" in code
        assert "left_active" in code
        assert "bi_flip_dn" in code
        # Must not gate entries on library 3buy marks
        assert "bs_type == '3buy'" not in code
        assert 'bs_type == "3buy"' not in code
        assert "isin(['1buy'" not in code
        desc = get_template(TRUE_3BUY_ID)["description"]
        assert "bs_type" in desc or "3buy" in desc
        assert "首次" in desc or "above" in desc

    def test_code_uses_czsc(self, code: str):
        assert code_uses_czsc(code) is True

    def test_dry_run_with_mock_columns(self, code: str):
        df = add_mock_czsc_columns(_make_ohlcv_df(100))
        out_df, output = _exec_template(code, df, {"trend_min": 0})
        for col in ("open_long", "close_long", "open_short", "close_short"):
            assert col in out_df.columns
            assert out_df[col].dtype == bool
        assert output is not None
        assert output["name"] == "真三买回踩确认 MVP"
        assert len(output.get("signals", [])) >= 2

    def test_validate_indicator_code(self, code: str):
        from app.services.indicator_validation import validate_indicator_code

        result = validate_indicator_code(code)
        assert result["success"] is True, (
            f"true_3buy_mvp validation failed: {result.get('msg')} | {result.get('details')}"
        )

    def test_synthetic_leave_pullback_fires_once(self, code: str):
        """Leave ZG alone must NOT fire; leave → pullback hold above ZG + bi_flip_dn fires."""
        n = 40
        dates = pd.date_range("2024-06-01", periods=n, freq="1h", tz="UTC")
        zg, zd = 100.0, 90.0
        close = np.full(n, 95.0)  # inside
        high = close + 1.0
        low = close - 1.0
        bi_dir = np.zeros(n, dtype=np.int8)
        zs_pos = np.array(["inside"] * n, dtype=object)
        trend = np.ones(n, dtype=np.int8)

        # bars 10-12: break and stay above (leave at 10)
        for i in range(10, 13):
            close[i] = 105.0
            high[i] = 107.0
            low[i] = 103.0
            zs_pos[i] = "above"
            bi_dir[i] = 1

        # bars 13-15: pullback toward ZG, still above; down stroke completes at 15
        for i in range(13, 16):
            close[i] = 101.0
            high[i] = 103.0
            low[i] = 100.2  # >= ZG, near ZG
            zs_pos[i] = "above"
            bi_dir[i] = -1

        df = pd.DataFrame(
            {
                "open": close.copy(),
                "high": high,
                "low": low,
                "close": close,
                "volume": np.full(n, 1500.0),
            },
            index=dates,
        )
        df = add_mock_czsc_columns(df)
        df["czsc_zs_level"] = 1
        df["czsc_zs_zd"] = zd
        df["czsc_zs_zg"] = zg
        df["czsc_zs_position"] = zs_pos
        df["czsc_bi_dir"] = bi_dir
        df["czsc_trend"] = trend

        out_df, _ = _exec_template(
            code,
            df,
            {
                "trend_min": 0,
                "require_amp_narrow": 0,
                "require_vol_surge": 0,
                "pullback_buffer": 0.05,
            },
        )

        # Leave bar (10) must not be open_long
        assert bool(out_df["open_long"].iloc[10]) is False
        # First bars still above without flip_dn edge after leave: 11-12 no
        assert int(out_df["open_long"].iloc[10:13].sum()) == 0
        # Confirmation at first bi_flip_dn while left_active & near ZG (bar 13:
        # bi_dir becomes -1 from 1)
        assert bool(out_df["open_long"].iloc[13]) is True
        assert int(out_df["open_long"].sum()) == 1

    def test_first_above_alone_does_not_fire(self, code: str):
        """Standing above without pullback confirm must not open_long."""
        n = 30
        dates = pd.date_range("2024-06-01", periods=n, freq="1h", tz="UTC")
        zg, zd = 100.0, 90.0
        close = np.full(n, 95.0)
        high = close + 1.0
        low = close - 1.0
        bi_dir = np.ones(n, dtype=np.int8)  # never flip_dn
        zs_pos = np.array(["inside"] * n, dtype=object)

        for i in range(8, n):
            close[i] = 110.0
            high[i] = 112.0
            low[i] = 108.0
            zs_pos[i] = "above"

        df = pd.DataFrame(
            {
                "open": close.copy(),
                "high": high,
                "low": low,
                "close": close,
                "volume": np.full(n, 1500.0),
            },
            index=dates,
        )
        df = add_mock_czsc_columns(df)
        df["czsc_zs_level"] = 1
        df["czsc_zs_zd"] = zd
        df["czsc_zs_zg"] = zg
        df["czsc_zs_position"] = zs_pos
        df["czsc_bi_dir"] = bi_dir
        df["czsc_trend"] = 1

        out_df, _ = _exec_template(code, df, {"require_amp_narrow": 0, "require_vol_surge": 0})
        assert int(out_df["open_long"].sum()) == 0

    def test_wick_below_zg_does_not_kill_left_before_confirm(self, code: str):
        """Intermediate lower-wick under ZG must not clear left_active; confirm still needs hold_above."""
        n = 40
        dates = pd.date_range("2024-06-01", periods=n, freq="1h", tz="UTC")
        zg, zd = 100.0, 90.0
        close = np.full(n, 95.0)
        high = close + 1.0
        low = close - 1.0
        bi_dir = np.zeros(n, dtype=np.int8)
        zs_pos = np.array(["inside"] * n, dtype=object)

        # leave above
        for i in range(10, 13):
            close[i] = 105.0
            high[i] = 107.0
            low[i] = 103.0
            zs_pos[i] = "above"
            bi_dir[i] = 1

        # intermediate bar: close still above, but wick dips below ZG
        close[13] = 102.0
        high[13] = 104.0
        low[13] = 99.0  # wick < ZG
        zs_pos[13] = "above"
        bi_dir[13] = 1

        # confirm: bi_flip_dn, hold above ZG
        for i in range(14, 16):
            close[i] = 101.0
            high[i] = 103.0
            low[i] = 100.2
            zs_pos[i] = "above"
            bi_dir[i] = -1

        df = pd.DataFrame(
            {
                "open": close.copy(),
                "high": high,
                "low": low,
                "close": close,
                "volume": np.full(n, 1500.0),
            },
            index=dates,
        )
        df = add_mock_czsc_columns(df)
        df["czsc_zs_level"] = 1
        df["czsc_zs_zd"] = zd
        df["czsc_zs_zg"] = zg
        df["czsc_zs_position"] = zs_pos
        df["czsc_bi_dir"] = bi_dir
        df["czsc_trend"] = 1

        out_df, _ = _exec_template(
            code,
            df,
            {"require_amp_narrow": 0, "require_vol_surge": 0, "pullback_buffer": 0.05},
        )
        assert bool(out_df["open_long"].iloc[14]) is True
        assert int(out_df["open_long"].sum()) == 1

    def test_close_back_into_zs_fires_close_long(self, code: str):
        """After leave, close/pos back inside must edge close_long (structure fail)."""
        n = 40
        dates = pd.date_range("2024-06-01", periods=n, freq="1h", tz="UTC")
        zg, zd = 100.0, 90.0
        close = np.full(n, 95.0)
        high = close + 1.0
        low = close - 1.0
        bi_dir = np.ones(n, dtype=np.int8)
        zs_pos = np.array(["inside"] * n, dtype=object)

        for i in range(10, 16):
            close[i] = 108.0
            high[i] = 110.0
            low[i] = 106.0
            zs_pos[i] = "above"

        # structure fail: close back inside
        close[16] = 98.0
        high[16] = 102.0
        low[16] = 97.0
        zs_pos[16] = "inside"

        df = pd.DataFrame(
            {
                "open": close.copy(),
                "high": high,
                "low": low,
                "close": close,
                "volume": np.full(n, 1500.0),
            },
            index=dates,
        )
        df = add_mock_czsc_columns(df)
        df["czsc_zs_level"] = 1
        df["czsc_zs_zd"] = zd
        df["czsc_zs_zg"] = zg
        df["czsc_zs_position"] = zs_pos
        df["czsc_bi_dir"] = bi_dir
        df["czsc_trend"] = 1

        out_df, _ = _exec_template(code, df, {"require_amp_narrow": 0, "require_vol_surge": 0})
        assert int(out_df["open_long"].sum()) == 0  # never confirmed
        assert bool(out_df["close_long"].iloc[16]) is True
