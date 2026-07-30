"""CZSC live/backtest signal synthesis (causal-reversal).

Live historically synthesized entries on short TFs because edge signals are sparse
in the lookback window. Higher TFs (15m+) keep structural overlays only:
zhongshu breakout stop-loss and reverse-when-opposed — not bare bi_dir flat entries
that would bypass indicator buy/sell filters.

Causal-reversal mapping (MUST match indicator):
  bi_dir == 1  (up stroke / top)    → prefer SHORT
  bi_dir == -1 (down stroke / bottom) → prefer LONG
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


FULL_SYNTH_TFS = frozenset({"10s", "1m", "3m", "5m"})
STRUCTURAL_SYNTH_TFS = frozenset({"15m", "30m", "1H", "4H"})

_TF_ALIASES = {
    "10s": "10s",
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "60m": "1H",
    "1H": "1H",
    "4h": "4H",
    "4H": "4H",
}


def normalize_czsc_timeframe(timeframe: str) -> str:
    raw = str(timeframe or "").strip()
    if not raw:
        return ""
    return _TF_ALIASES.get(raw, _TF_ALIASES.get(raw.lower(), raw))


def czsc_synth_mode(timeframe: str) -> Optional[str]:
    """Return default mode for timeframe: 'full', 'structural', or None.

    Defaults are unchanged: short TFs → full; 15m–4H → structural.
    """
    tf = normalize_czsc_timeframe(timeframe)
    if tf in FULL_SYNTH_TFS:
        return "full"
    if tf in STRUCTURAL_SYNTH_TFS:
        return "structural"
    return None


def resolve_czsc_synth_mode(
    timeframe: str,
    override: Optional[str] = None,
) -> Optional[str]:
    """Resolve synth mode with optional explicit override (backtest / experiments).

    override:
      - None / '': use czsc_synth_mode(timeframe) default
      - 'off' / 'none' / 'disabled': disable synthesis
      - 'full' | 'structural' | 'reverse': force that mode
    """
    raw = str(override or "").strip().lower()
    if raw in ("off", "none", "disabled", "0", "false"):
        return None
    if raw in ("full", "structural", "reverse"):
        return raw
    if raw:
        # Unknown override → fall back to default rather than silently no-op
        return czsc_synth_mode(timeframe)
    return czsc_synth_mode(timeframe)


@dataclass
class CzscSynthDecision:
    close_long: bool = False
    close_short: bool = False
    open_long: bool = False
    open_short: bool = False
    notes: List[str] = field(default_factory=list)


def evaluate_czsc_synth(
    *,
    mode: str,
    position: int,
    curr_bi: int,
    last_close: float,
    trade_dir: str,
    has_entry: bool,
    has_zs: bool = False,
    zs_zd: float = 0.0,
    zs_zg: float = 0.0,
    zs_pos: str = "",
    bi_len: int = 0,
    min_bi_len: int = 3,
) -> CzscSynthDecision:
    """Evaluate CZSC synthesis for one bar / live tick.

    mode:
      - full: zs stop + reverse + flat entry from bi_dir when no indicator entry
      - structural: zs stop + reverse only (no flat bi_dir entry)  [default 15m+]
      - reverse: reverse only (no zs stop, no flat bi_dir entry)   [new split]
    """
    out = CzscSynthDecision()

    # ---- New split: reverse-only (do not alter full/structural paths below) ----
    if mode == "reverse":
        pos = int(position or 0)
        if pos > 0:
            pos = 1
        elif pos < 0:
            pos = -1
        else:
            pos = 0
        bi = int(curr_bi or 0)
        td = str(trade_dir or "both").strip().lower()
        if td not in ("long", "short", "both"):
            td = "both"
        close = float(last_close or 0.0)
        bi_long_enough = int(bi_len or 0) >= int(min_bi_len or 3)
        zs_pos_s = str(zs_pos or "")
        zd = float(zs_zd or 0.0)
        zg = float(zs_zg or 0.0)

        if has_entry:
            return out

        def _skip_long_entry() -> bool:
            if has_zs and zs_pos_s == "inside":
                out.notes.append("skip long: inside zhongshu")
                return True
            if has_zs and zs_pos_s and zs_pos_s != "inside" and zd > 0 and zg > 0:
                if close < zd and bi == -1:
                    out.notes.append(f"skip long: price {close:.4f}<zd={zd:.4f} would stop")
                    return True
            if not bi_long_enough:
                out.notes.append(f"skip long: bi_len={bi_len}<{min_bi_len}")
                return True
            return False

        def _skip_short_entry() -> bool:
            if has_zs and zs_pos_s == "inside":
                out.notes.append("skip short: inside zhongshu")
                return True
            if has_zs and zs_pos_s and zs_pos_s != "inside" and zd > 0 and zg > 0:
                if close > zg and bi == 1:
                    out.notes.append(f"skip short: price {close:.4f}>zg={zg:.4f} would stop")
                    return True
            if not bi_long_enough:
                out.notes.append(f"skip short: bi_len={bi_len}<{min_bi_len}")
                return True
            return False

        if pos == 1 and bi == 1:
            out.close_long = True
            if td in ("short", "both") and not _skip_short_entry():
                if has_zs and zg > 0 and close > zg:
                    out.notes.append(f"skip reverse short: price {close:.4f}>zg={zg:.4f}")
                else:
                    out.open_short = True
            return out

        if pos == -1 and bi == -1:
            out.close_short = True
            if td in ("long", "both") and not _skip_long_entry():
                if has_zs and zd > 0 and close < zd:
                    out.notes.append(f"skip reverse long: price {close:.4f}<zd={zd:.4f}")
                else:
                    out.open_long = True
            return out

        return out

    if mode not in ("full", "structural"):
        return out

    pos = int(position or 0)
    if pos > 0:
        pos = 1
    elif pos < 0:
        pos = -1
    else:
        pos = 0

    bi = int(curr_bi or 0)
    td = str(trade_dir or "both").strip().lower()
    if td not in ("long", "short", "both"):
        td = "both"
    close = float(last_close or 0.0)
    bi_long_enough = int(bi_len or 0) >= int(min_bi_len or 3)
    zs_pos_s = str(zs_pos or "")
    zd = float(zs_zd or 0.0)
    zg = float(zs_zg or 0.0)

    # Part A: Zhongshu breakout stop-loss
    if has_zs and zd > 0 and zg > 0:
        if pos == 1 and close < zd:
            out.close_long = True
            out.notes.append(f"zs_stop close_long price={close:.4f}<zd={zd:.4f}")
        elif pos == -1 and close > zg:
            out.close_short = True
            out.notes.append(f"zs_stop close_short price={close:.4f}>zg={zg:.4f}")

    # Part B only when indicator did not already emit an entry this window/bar
    if has_entry:
        return out

    allow_flat_entry = mode == "full"

    def _skip_long_entry() -> bool:
        if has_zs and zs_pos_s == "inside":
            out.notes.append("skip long: inside zhongshu")
            return True
        if has_zs and zs_pos_s and zs_pos_s != "inside" and zd > 0 and zg > 0:
            if close < zd and bi == -1:
                out.notes.append(f"skip long: price {close:.4f}<zd={zd:.4f} would stop")
                return True
        if not bi_long_enough:
            out.notes.append(f"skip long: bi_len={bi_len}<{min_bi_len}")
            return True
        return False

    def _skip_short_entry() -> bool:
        if has_zs and zs_pos_s == "inside":
            out.notes.append("skip short: inside zhongshu")
            return True
        if has_zs and zs_pos_s and zs_pos_s != "inside" and zd > 0 and zg > 0:
            if close > zg and bi == 1:
                out.notes.append(f"skip short: price {close:.4f}>zg={zg:.4f} would stop")
                return True
        if not bi_long_enough:
            out.notes.append(f"skip short: bi_len={bi_len}<{min_bi_len}")
            return True
        return False

    # Flat → optional entry (full mode only)
    if allow_flat_entry and pos == 0 and bi != 0:
        if bi == 1 and td in ("short", "both") and not _skip_short_entry():
            out.open_short = True
        elif bi == -1 and td in ("long", "both") and not _skip_long_entry():
            out.open_long = True
        return out

    # Position opposes causal target → close + reverse
    if pos == 1 and bi == 1:
        out.close_long = True
        if td in ("short", "both") and not _skip_short_entry():
            # Extra anti-whipsaw for reverse: price already above zg
            if has_zs and zg > 0 and close > zg:
                out.notes.append(f"skip reverse short: price {close:.4f}>zg={zg:.4f}")
            else:
                out.open_short = True
        return out

    if pos == -1 and bi == -1:
        out.close_short = True
        if td in ("long", "both") and not _skip_long_entry():
            if has_zs and zd > 0 and close < zd:
                out.notes.append(f"skip reverse long: price {close:.4f}<zd={zd:.4f}")
            else:
                out.open_long = True
        return out

    return out


def apply_czsc_anti_whipsaw(
    *,
    position: int,
    last_close: float,
    open_long: bool,
    open_short: bool,
    close_long: bool,
    close_short: bool,
    has_zs: bool,
    zs_zd: float,
    zs_zg: float,
) -> tuple[bool, bool, bool, bool, List[str]]:
    """Live Part C anti-whipsaw — shared by live executor and backtest enrich.

    Returns updated (open_long, open_short, close_long, close_short, notes).
    """
    notes: List[str] = []
    ol, os_, cl, cs = bool(open_long), bool(open_short), bool(close_long), bool(close_short)
    if not (has_zs and float(zs_zd or 0) > 0 and float(zs_zg or 0) > 0):
        return ol, os_, cl, cs, notes

    zd = float(zs_zd)
    zg = float(zs_zg)
    close = float(last_close or 0.0)
    pos = int(position or 0)
    if pos > 0:
        pos = 1
    elif pos < 0:
        pos = -1
    else:
        pos = 0

    # Same-direction close+open → drop entry (prevent open→close loop)
    if cl and ol:
        ol = False
        notes.append("anti-whipsaw: removed open_long (close_long pending)")
    if cs and os_:
        os_ = False
        notes.append("anti-whipsaw: removed open_short (close_short pending)")

    # Flat + price already in stop zone → block entries that zs_stop would kill
    if pos == 0:
        if close < zd and ol:
            ol = False
            notes.append(f"anti-whipsaw: blocked open_long price={close:.4f}<zd={zd:.4f}")
        if close > zg and os_:
            os_ = False
            notes.append(f"anti-whipsaw: blocked open_short price={close:.4f}>zg={zg:.4f}")

    return ol, os_, cl, cs, notes


def enrich_signals_with_czsc_synth(
    df,
    signals: dict,
    timeframe: str,
    trade_dir: str = "both",
    mode_override: Optional[str] = None,
    fill_lag: int = 1,
) -> dict:
    """OR CZSC synthesis into backtest signal series (causal walk, shadow position).

    Must run BEFORE next_bar_open shifting so synth signals share fill timing
    with indicator signals.

    fill_lag:
      - 1 (default): match next_bar_open — bar-i signals fill at start of bar i+1,
        so evaluation uses position after prior-bar fills only.
      - 0: same-bar fill shadow (legacy / bar_close timing).

    Also applies live Part C anti-whipsaw so stop-zone re-entries are blocked.
    """
    mode = resolve_czsc_synth_mode(timeframe, mode_override)
    if mode is None:
        return signals
    if df is None or "czsc_bi_dir" not in getattr(df, "columns", []):
        raise ValueError(
            f"[CZSC_SYNTH] mode={mode} requires czsc_bi_dir on df "
            f"(tf={timeframe}); columns missing — refusing silent skip"
        )
    if not all(k in signals for k in ("open_long", "close_long", "open_short", "close_short")):
        raise ValueError("[CZSC_SYNTH] signals must include four-way open/close columns")

    import numpy as np
    import pandas as pd

    n = len(df)
    if n == 0:
        return signals

    lag = 1 if int(fill_lag or 0) >= 1 else 0

    ol = signals["open_long"].reindex(df.index, fill_value=False).fillna(False).astype(bool).to_numpy().copy()
    cl = signals["close_long"].reindex(df.index, fill_value=False).fillna(False).astype(bool).to_numpy().copy()
    os_ = signals["open_short"].reindex(df.index, fill_value=False).fillna(False).astype(bool).to_numpy().copy()
    cs = signals["close_short"].reindex(df.index, fill_value=False).fillna(False).astype(bool).to_numpy().copy()

    bi_arr = pd.to_numeric(df["czsc_bi_dir"], errors="coerce").fillna(0).to_numpy()
    close_arr = pd.to_numeric(df["close"], errors="coerce").fillna(0.0).to_numpy()

    has_zs_cols = all(c in df.columns for c in ("czsc_zs_zd", "czsc_zs_zg", "czsc_zs_position"))
    if has_zs_cols:
        zd_arr = pd.to_numeric(df["czsc_zs_zd"], errors="coerce").fillna(0.0).to_numpy()
        zg_arr = pd.to_numeric(df["czsc_zs_zg"], errors="coerce").fillna(0.0).to_numpy()
        zs_pos_arr = df["czsc_zs_position"].fillna("").astype(str).to_numpy()
    else:
        zd_arr = np.zeros(n)
        zg_arr = np.zeros(n)
        zs_pos_arr = np.array([""] * n, dtype=object)

    if "czsc_bi_length" in df.columns:
        bi_len_arr = pd.to_numeric(df["czsc_bi_length"], errors="coerce").fillna(0).to_numpy()
    else:
        bi_len_arr = np.zeros(n)

    def _apply_fills(pos_now: int, f_ol: bool, f_os: bool, f_cl: bool, f_cs: bool) -> int:
        if pos_now > 0 and (f_cl or f_os):
            pos_now = 0
        if pos_now < 0 and (f_cs or f_ol):
            pos_now = 0
        if pos_now == 0:
            if f_ol:
                pos_now = 1
            elif f_os:
                pos_now = -1
        return pos_now

    pos = 0
    pending_ol = pending_os = pending_cl = pending_cs = False
    synth_opens = 0
    synth_closes = 0
    aw_blocks = 0

    for i in range(n):
        if lag:
            pos = _apply_fills(pos, pending_ol, pending_os, pending_cl, pending_cs)
            pending_ol = pending_os = pending_cl = pending_cs = False

        has_entry = bool(ol[i] or os_[i])
        zd = float(zd_arr[i] or 0.0)
        zg = float(zg_arr[i] or 0.0)
        close_i = float(close_arr[i] or 0.0)
        has_zs = has_zs_cols and zd > 0 and zg > 0

        decision = evaluate_czsc_synth(
            mode=mode,
            position=pos,
            curr_bi=int(bi_arr[i] or 0),
            last_close=close_i,
            trade_dir=trade_dir,
            has_entry=has_entry,
            has_zs=has_zs,
            zs_zd=zd,
            zs_zg=zg,
            zs_pos=str(zs_pos_arr[i] or ""),
            bi_len=int(bi_len_arr[i] or 0),
        )
        if decision.close_long and not cl[i]:
            cl[i] = True
            synth_closes += 1
        if decision.close_short and not cs[i]:
            cs[i] = True
            synth_closes += 1
        if decision.open_long and not ol[i]:
            ol[i] = True
            synth_opens += 1
        if decision.open_short and not os_[i]:
            os_[i] = True
            synth_opens += 1

        # Part C anti-whipsaw (same rules as live), using pre-fill position
        ol_b, os_b, cl_b, cs_b, aw_notes = apply_czsc_anti_whipsaw(
            position=pos,
            last_close=close_i,
            open_long=bool(ol[i]),
            open_short=bool(os_[i]),
            close_long=bool(cl[i]),
            close_short=bool(cs[i]),
            has_zs=has_zs,
            zs_zd=zd,
            zs_zg=zg,
        )
        if aw_notes:
            aw_blocks += len(aw_notes)
        ol[i], os_[i], cl[i], cs[i] = ol_b, os_b, cl_b, cs_b

        if lag:
            pending_ol, pending_os, pending_cl, pending_cs = bool(ol[i]), bool(os_[i]), bool(cl[i]), bool(cs[i])
        else:
            pos = _apply_fills(pos, bool(ol[i]), bool(os_[i]), bool(cl[i]), bool(cs[i]))

    out = dict(signals)
    idx = df.index
    out["open_long"] = pd.Series(ol, index=idx)
    out["close_long"] = pd.Series(cl, index=idx)
    out["open_short"] = pd.Series(os_, index=idx)
    out["close_short"] = pd.Series(cs, index=idx)
    out["_czsc_synth"] = {
        "mode": mode,
        "opens": synth_opens,
        "closes": synth_closes,
        "fill_lag": lag,
        "anti_whipsaw_blocks": aw_blocks,
    }
    return out
