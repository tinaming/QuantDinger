"""Unit tests for shared CZSC live/backtest signal synthesis."""
from app.services.czsc_synth import (
    apply_czsc_anti_whipsaw,
    czsc_synth_mode,
    enrich_signals_with_czsc_synth,
    evaluate_czsc_synth,
    resolve_czsc_synth_mode,
)


def test_synth_mode_full_vs_structural():
    assert czsc_synth_mode("5m") == "full"
    assert czsc_synth_mode("1m") == "full"
    assert czsc_synth_mode("15m") == "structural"
    assert czsc_synth_mode("30m") == "structural"
    assert czsc_synth_mode("1H") == "structural"
    assert czsc_synth_mode("1h") == "structural"
    assert czsc_synth_mode("1d") is None


def test_resolve_override():
    assert resolve_czsc_synth_mode("15m", None) == "structural"
    assert resolve_czsc_synth_mode("15m", "reverse") == "reverse"
    assert resolve_czsc_synth_mode("15m", "off") is None
    assert resolve_czsc_synth_mode("5m", "structural") == "structural"


def test_structural_mode_skips_flat_bi_dir_entry():
    d = evaluate_czsc_synth(
        mode="structural",
        position=0,
        curr_bi=-1,
        last_close=100.0,
        trade_dir="both",
        has_entry=False,
        bi_len=5,
    )
    assert not d.open_long
    assert not d.open_short


def test_full_mode_allows_flat_bi_dir_entry():
    d = evaluate_czsc_synth(
        mode="full",
        position=0,
        curr_bi=-1,
        last_close=100.0,
        trade_dir="both",
        has_entry=False,
        bi_len=5,
    )
    assert d.open_long
    assert not d.open_short


def test_structural_mode_still_reverses_opposed_position():
    d = evaluate_czsc_synth(
        mode="structural",
        position=1,
        curr_bi=1,
        last_close=100.0,
        trade_dir="both",
        has_entry=False,
        bi_len=5,
    )
    assert d.close_long
    assert d.open_short


def test_reverse_mode_no_zs_stop_but_still_reverses():
    d = evaluate_czsc_synth(
        mode="reverse",
        position=1,
        curr_bi=-1,
        last_close=90.0,
        trade_dir="both",
        has_entry=False,
        has_zs=True,
        zs_zd=95.0,
        zs_zg=105.0,
        zs_pos="below",
        bi_len=5,
    )
    assert not d.close_long
    assert not d.open_short

    d2 = evaluate_czsc_synth(
        mode="reverse",
        position=1,
        curr_bi=1,
        last_close=100.0,
        trade_dir="both",
        has_entry=False,
        bi_len=5,
    )
    assert d2.close_long
    assert d2.open_short


def test_zs_stop_fires_even_with_indicator_entry():
    d = evaluate_czsc_synth(
        mode="structural",
        position=1,
        curr_bi=-1,
        last_close=90.0,
        trade_dir="both",
        has_entry=True,
        has_zs=True,
        zs_zd=95.0,
        zs_zg=105.0,
        zs_pos="below",
        bi_len=5,
    )
    assert d.close_long
    assert not d.open_short


def test_anti_whipsaw_blocks_flat_entry_in_stop_zone():
    ol, os_, cl, cs, notes = apply_czsc_anti_whipsaw(
        position=0,
        last_close=90.0,
        open_long=True,
        open_short=False,
        close_long=False,
        close_short=False,
        has_zs=True,
        zs_zd=95.0,
        zs_zg=105.0,
    )
    assert not ol
    assert notes


def test_anti_whipsaw_drops_same_dir_open_when_close_pending():
    ol, os_, cl, cs, notes = apply_czsc_anti_whipsaw(
        position=1,
        last_close=100.0,
        open_long=True,
        open_short=False,
        close_long=True,
        close_short=False,
        has_zs=True,
        zs_zd=95.0,
        zs_zg=105.0,
    )
    assert not ol
    assert cl


def test_enrich_signals_structural_no_flat_spam():
    import pandas as pd

    idx = pd.date_range("2026-01-01", periods=4, freq="15min")
    df = pd.DataFrame(
        {
            "close": [100.0, 101.0, 102.0, 103.0],
            "czsc_bi_dir": [-1, -1, 1, 1],
            "czsc_bi_length": [5, 6, 5, 6],
            "czsc_zs_zd": [0.0, 0.0, 0.0, 0.0],
            "czsc_zs_zg": [0.0, 0.0, 0.0, 0.0],
            "czsc_zs_position": ["", "", "", ""],
        },
        index=idx,
    )
    false = pd.Series([False] * 4, index=idx)
    signals = {
        "open_long": false.copy(),
        "close_long": false.copy(),
        "open_short": false.copy(),
        "close_short": false.copy(),
    }
    out = enrich_signals_with_czsc_synth(df, signals, "15m", "both")
    assert int(out["open_long"].sum()) == 0
    assert int(out["open_short"].sum()) == 0
    assert out["_czsc_synth"]["mode"] == "structural"
    assert out["_czsc_synth"]["fill_lag"] == 1

    out_rev = enrich_signals_with_czsc_synth(df, signals, "15m", "both", mode_override="reverse")
    assert out_rev["_czsc_synth"]["mode"] == "reverse"


def test_enrich_part_c_blocks_indicator_reentry_in_stop_zone():
    """After flat, indicator open_long below zd must be stripped (live Part C)."""
    import pandas as pd

    idx = pd.date_range("2026-01-01", periods=3, freq="15min")
    df = pd.DataFrame(
        {
            "close": [100.0, 90.0, 89.0],
            "czsc_bi_dir": [-1, -1, -1],
            "czsc_bi_length": [5, 6, 7],
            "czsc_zs_zd": [95.0, 95.0, 95.0],
            "czsc_zs_zg": [105.0, 105.0, 105.0],
            "czsc_zs_position": ["inside", "below", "below"],
        },
        index=idx,
    )
    signals = {
        "open_long": pd.Series([False, True, True], index=idx),
        "close_long": pd.Series([False, False, False], index=idx),
        "open_short": pd.Series([False, False, False], index=idx),
        "close_short": pd.Series([False, False, False], index=idx),
    }
    out = enrich_signals_with_czsc_synth(df, signals, "15m", "both", fill_lag=1)
    assert not bool(out["open_long"].iloc[1])
    assert not bool(out["open_long"].iloc[2])
    assert out["_czsc_synth"]["anti_whipsaw_blocks"] >= 1


def test_enrich_missing_czsc_cols_raises():
    import pandas as pd
    import pytest

    idx = pd.date_range("2026-01-01", periods=2, freq="15min")
    df = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
    false = pd.Series([False, False], index=idx)
    signals = {
        "open_long": false.copy(),
        "close_long": false.copy(),
        "open_short": false.copy(),
        "close_short": false.copy(),
    }
    with pytest.raises(ValueError, match="czsc_bi_dir"):
        enrich_signals_with_czsc_synth(df, signals, "15m", "both")
