# -*- coding: utf-8 -*-
"""Add Chan/CZSC strategy prompt examples to Copilot UI (策略提示示例 + i18n + skill starters)."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
ASSETS = ROOT / "html" / "assets"
sys.path.insert(0, str(ROOT))
from _ide_chunk import resolve_main_entry  # noqa: E402

# New indicator-side examples (titles + full prompts). Keep system-admin chips untouched.
NEW_EXAMPLES = [
    {
        "key": "czsc-structure",
        "title_key": "strategyExampleCzscStructure",
        "title_zh": "缠论结构买卖点",
        "title_en": "Chan structure BS points",
        "prompt_key": "strategyExamples.czscStructure",
        "prompt_zh": (
            "请分析 {symbol} 当前级别的笔、线段、中枢与买卖点（若有），"
            "明确位置与失效条件，并给出等待/行动建议；优先用系统 CZSC 结果，禁止编造结构。"
        ),
        "prompt_en": (
            "Analyze {symbol} bi/duan/zhongshu and buy/sell points at the current timeframe; "
            "state position, invalidation, and wait-or-act guidance. Prefer system CZSC — do not invent structure."
        ),
        "fallback_en": (
            "Analyze {symbol} bi/duan/zhongshu and buy/sell points; give invalidation and wait-or-act guidance "
            "using system CZSC results."
        ),
    },
    {
        "key": "czsc-multilevel",
        "title_key": "strategyExampleCzscMultilevel",
        "title_zh": "多级别联立",
        "title_en": "Multi-timeframe Chan",
        "prompt_key": "strategyExamples.czscMultilevel",
        "prompt_zh": (
            "请对 {symbol} 做 30 分钟 + 5 分钟多级别联立：大级别定方向与中枢，小级别找买卖点；"
            "说明级别冲突时如何处理，并给出可执行操作建议。"
        ),
        "prompt_en": (
            "Run a 30m + 5m multi-timeframe Chan review for {symbol}: higher TF sets direction/zhongshu, "
            "lower TF finds BS points; explain conflicts and give actionable guidance."
        ),
        "fallback_en": (
            "Multi-timeframe Chan for {symbol} (30m + 5m): HTF direction/zhongshu, LTF BS points, conflict handling."
        ),
    },
    {
        "key": "czsc-123-bs",
        "title_key": "strategyExampleCzsc123",
        "title_zh": "一二三类买卖点",
        "title_en": "Class 1/2/3 BS strategy",
        "prompt_key": "strategyExamples.czsc123",
        "prompt_zh": (
            "请为 {symbol} 设计基于一类/二类/三类买卖点的短线策略草稿："
            "默认四路 open_*/close_* + 边缘触发，声明 signal_form/exit_owner/flip_mode；"
            "优先预计算 czsc_* 列，禁止 import czsc；并给出回测验证步骤。"
        ),
        "prompt_en": (
            "Draft a short-term strategy for {symbol} based on class-1/2/3 Chan buy/sell points: "
            "four_way open_*/close_* + edge trigger; declare signal_form/exit_owner/flip_mode; "
            "prefer czsc_* columns (never import czsc); include backtest steps."
        ),
        "fallback_en": (
            "Class 1/2/3 Chan short-term strategy for {symbol} with four_way edge signals and backtest steps."
        ),
    },
    {
        "key": "czsc-zs-vs-trend",
        "title_key": "strategyExampleCzscZsVsTrend",
        "title_zh": "中枢震荡vs趋势",
        "title_en": "Zhongshu range vs trend",
        "prompt_key": "strategyExamples.czscZsVsTrend",
        "prompt_zh": (
            "请判断 {symbol} 当前更像中枢震荡还是趋势延伸，并给出对应操作建议："
            "震荡侧重高抛低吸与边界失效；趋势侧重顺势持有、不逆势追单；说明切换条件。"
        ),
        "prompt_en": (
            "Decide whether {symbol} is in zhongshu range or trend extension, then advise: "
            "range = fade extremes with invalidation; trend = hold with trend, no counter-chase; state switch conditions."
        ),
        "fallback_en": (
            "Is {symbol} zhongshu range or trend extension? Give matching playbook and switch conditions."
        ),
    },
    {
        "key": "trend-5m-boll",
        "title_key": "strategyExampleTrend5mBoll",
        "title_zh": "趋势+5m布林",
        "title_en": "Trend + 5m Bollinger",
        "prompt_key": "strategyExamples.trend5mBoll",
        "prompt_zh": (
            "{symbol} 若趋势已极明确，请用 5 分钟布林带做简洁趋势跟随辅助，"
            "说明为何此时可不强依赖缠论结构；输出对齐四路信号与 exit_owner，并给回测步骤。"
        ),
        "prompt_en": (
            "Trend on {symbol} is already clear: design a simple 5m Bollinger trend-follow assist, "
            "explain why Chan structure is optional now; align four_way signals + exit_owner; include backtest steps."
        ),
        "fallback_en": (
            "Clear-trend 5m Bollinger assist for {symbol}; optional Chan; four_way + exit_owner + backtest steps."
        ),
    },
    {
        "key": "czsc-signal-draft",
        "title_key": "strategyExampleCzscSignalDraft",
        "title_zh": "信号标准短线稿",
        "title_en": "Signal-standard Chan draft",
        "prompt_key": "strategyExamples.czscSignalDraft",
        "prompt_zh": (
            "请为 {symbol} 写出符合平台 SIGNAL_EXECUTION_STANDARD 的缠论短线策略草稿："
            "四路信号、边缘触发、声明 signal_form/exit_owner/flip_mode；优先 czsc_*；禁止 import czsc；含验证与回测计划。"
        ),
        "prompt_en": (
            "Write a Chan short-term draft for {symbol} that follows SIGNAL_EXECUTION_STANDARD: "
            "four_way + edge; declare signal_form/exit_owner/flip_mode; prefer czsc_*; never import czsc; include validation/backtest plan."
        ),
        "fallback_en": (
            "SIGNAL_EXECUTION_STANDARD Chan short-term draft for {symbol}: four_way edge, czsc_*, backtest plan."
        ),
    },
]


def _write_text_lf(path: pathlib.Path, text: str) -> None:
    path.write_bytes(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))


def _patch_file(path: pathlib.Path, replacements: list[tuple[str, str]]) -> int:
    if not path.exists():
        print(f"missing {path}")
        return 0
    raw = path.read_bytes()
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    had_cr = b"\r" in raw
    changed = 0
    for old, new in replacements:
        count = text.count(old)
        if count == 0:
            if new and text.count(new) > 0:
                print(f"  SKIP  {path.name}: already applied {new[:70]!r}")
                continue
            print(f"  MISS  {path.name}: {old[:90]!r}")
            continue
        if old == new:
            continue
        text = text.replace(old, new)
        changed += count
        print(f"  OK    {path.name}: {count}x {old[:70]!r}")
    if changed or had_cr:
        _write_text_lf(path, text)
        if had_cr and not changed:
            print(f"  OK    {path.name}: normalized CRLF -> LF")
    return changed


def _js_indicator_entries() -> str:
    parts = []
    for ex in NEW_EXAMPLES:
        parts.append(
            "{"
            f'key:"{ex["key"]}",targetType:"indicator",'
            f'title:this.text.{ex["title_key"]},'
            f'prompt:this.i18nText("aiAssetAnalysis.copilot.{ex["prompt_key"]}",'
            f'"{ex["fallback_en"]}",{{symbol:t}})'
            "}"
        )
    return ",".join(parts)


def _js_text_bindings() -> str:
    parts = []
    for ex in NEW_EXAMPLES:
        parts.append(
            f'{ex["title_key"]}:e("{ex["title_key"]}","{ex["title_en"]}")'
        )
    return ",".join(parts)


def patch_chip_bundle() -> int:
    path = ASSETS / "index-CQcKXJTG.js"
    old_indicator = (
        's={indicator:[{key:"momentum-breakout",targetType:"indicator",'
        'title:this.text.strategyExampleMomentum,'
        'prompt:this.i18nText("aiAssetAnalysis.copilot.strategyExamples.momentum",'
        '"{symbol} 15m momentum breakout: go long when ROC > 0 and volume breaks above average, '
        'hold above EMA10, stop loss 2%, take profit 5%, backtest 6 months.",{symbol:t})},'
        '{key:"mean-reversion",targetType:"indicator",'
        'title:this.text.strategyExampleReversal,'
        'prompt:this.i18nText("aiAssetAnalysis.copilot.strategyExamples.reversal",'
        '"{symbol} 1h mean reversion: short when price touches upper Bollinger Band and RSI > 70, '
        'long when lower band and RSI < 30, exit at middle band, stop loss 2%, take profit 3%.",{symbol:t})}]'
    )
    # Prefer idempotent: if already has czsc-structure, skip structural replace
    text = path.read_text(encoding="utf-8")
    if 'key:"czsc-structure"' in text:
        print(f"  SKIP  {path.name}: indicator Chan examples already present")
        n = 0
    else:
        new_indicator = (
            "s={indicator:["
            + _js_indicator_entries()
            + ',{key:"momentum-breakout",targetType:"indicator",'
            'title:this.text.strategyExampleMomentum,'
            'prompt:this.i18nText("aiAssetAnalysis.copilot.strategyExamples.momentum",'
            '"{symbol} 15m momentum breakout: go long when ROC > 0 and volume breaks above average, '
            'hold above EMA10, stop loss 2%, take profit 5%, backtest 6 months.",{symbol:t})},'
            '{key:"mean-reversion",targetType:"indicator",'
            'title:this.text.strategyExampleReversal,'
            'prompt:this.i18nText("aiAssetAnalysis.copilot.strategyExamples.reversal",'
            '"{symbol} 1h mean reversion: short when price touches upper Bollinger Band and RSI > 70, '
            'long when lower band and RSI < 30, exit at middle band, stop loss 2%, take profit 3%.",{symbol:t})}]'
        )
        n = _patch_file(path, [(old_indicator, new_indicator)])

    # text() title bindings (check for the e() binding, not mere title-key mentions)
    old_text = (
        'strategyExampleTrendTemplate:e("strategyExampleTrendTemplate","Trend template"),'
        'calendarUnavailable:e("calendarUnavailable","Calendar unavailable")'
    )
    if 'strategyExampleCzscStructure:e(' in path.read_text(encoding="utf-8"):
        print(f"  SKIP  {path.name}: text() Chan titles already present")
        return n
    new_text = (
        'strategyExampleTrendTemplate:e("strategyExampleTrendTemplate","Trend template"),'
        + _js_text_bindings()
        + ","
        'calendarUnavailable:e("calendarUnavailable","Calendar unavailable")'
    )
    return n + _patch_file(path, [(old_text, new_text)])


def patch_zh_cn() -> int:
    path = ASSETS / "zh-CN-9JXFFF04.js"
    text = path.read_text(encoding="utf-8")
    if "strategyExampleCzscStructure" in text:
        print(f"  SKIP  {path.name}: Chan strategy example i18n already present")
        return 0

    # Insert title keys after strategyExampleTrendTemplate title
    title_insert = "".join(
        f',"aiAssetAnalysis.copilot.{ex["title_key"]}":"{ex["title_zh"]}"' for ex in NEW_EXAMPLES
    )
    prompt_insert = "".join(
        f',"aiAssetAnalysis.copilot.{ex["prompt_key"]}":"{ex["prompt_zh"]}"' for ex in NEW_EXAMPLES
    )

    reps = [
        (
            'aiAssetAnalysis.copilot.strategyExampleTrendTemplate":"趋势模板"',
            'aiAssetAnalysis.copilot.strategyExampleTrendTemplate":"趋势模板"' + title_insert,
        ),
        (
            'aiAssetAnalysis.copilot.strategyExamples.trendTemplate":"为 {symbol} 创建趋势跟随模板策略方案：入场触发、移动止损、止盈逻辑、仓位大小和人工复核清单。"',
            'aiAssetAnalysis.copilot.strategyExamples.trendTemplate":"为 {symbol} 创建趋势跟随模板策略方案：入场触发、移动止损、止盈逻辑、仓位大小和人工复核清单。"'
            + prompt_insert,
        ),
        # Enrich dedicated trading chip prompts (keep system skills unchanged)
        (
            'aiAssetAnalysis.copilot.quickPrompts.czsc":"请对 {symbol} 做缠论结构复盘：明确级别、中枢位置、买卖点（若有）、失效条件与等待/行动建议；优先用系统 CZSC 结果，禁止编造结构。"',
            'aiAssetAnalysis.copilot.quickPrompts.czsc":"请对 {symbol} 做缠论结构复盘：明确级别，标出笔/线段/中枢与买卖点（若有），可补充 30m+5m 联立；给出失效条件与等待/行动建议；优先用系统 CZSC，禁止编造结构。"',
        ),
        (
            'aiAssetAnalysis.copilot.quickPrompts.chan_short":"请为 {symbol} 写可执行短线策略（优先缠论；趋势明确可用 5m 布林），对齐四路信号与 exit_owner，并给出回测步骤。"',
            'aiAssetAnalysis.copilot.quickPrompts.chan_short":"请为 {symbol} 写可执行短线策略：优先一类/二类/三类买卖点或中枢进出；趋势极明确可用 5m 布林辅助；对齐四路信号与 exit_owner/flip_mode，并给出回测步骤。"',
        ),
        (
            'aiAssetAnalysis.copilot.quickTasks.czsc_analysis.desc":"交易分析：分型/笔/中枢与买卖点。"',
            'aiAssetAnalysis.copilot.quickTasks.czsc_analysis.desc":"笔/线段/中枢、买卖点与多级别联立。"',
        ),
        (
            'aiAssetAnalysis.copilot.quickTasks.chan_short_strategy.desc":"缠论短线，或趋势明确时用 5m 布林。"',
            'aiAssetAnalysis.copilot.quickTasks.chan_short_strategy.desc":"一二三类买卖点短线，或趋势明确时 5m 布林。"',
        ),
    ]
    return _patch_file(path, reps)


def patch_en_index() -> int:
    path = resolve_main_entry()
    if path is None:
        print("missing main entry")
        return 0
    text = path.read_text(encoding="utf-8")
    if "strategyExampleCzscStructure" in text:
        print(f"  SKIP  {path.name}: Chan strategy example i18n already present")
        return 0

    title_insert = "".join(
        f',"aiAssetAnalysis.copilot.{ex["title_key"]}":"{ex["title_en"]}"' for ex in NEW_EXAMPLES
    )
    prompt_insert = "".join(
        f',"aiAssetAnalysis.copilot.{ex["prompt_key"]}":"{ex["prompt_en"]}"' for ex in NEW_EXAMPLES
    )
    reps = [
        (
            'aiAssetAnalysis.copilot.strategyExampleTrendTemplate":"Trend template"',
            'aiAssetAnalysis.copilot.strategyExampleTrendTemplate":"Trend template"' + title_insert,
        ),
        (
            'aiAssetAnalysis.copilot.strategyExamples.trendTemplate":"Create a trend-following template strategy plan for {symbol}: entry trigger, trailing stop, take-profit logic, position size, and manual review checklist."',
            'aiAssetAnalysis.copilot.strategyExamples.trendTemplate":"Create a trend-following template strategy plan for {symbol}: entry trigger, trailing stop, take-profit logic, position size, and manual review checklist."'
            + prompt_insert,
        ),
    ]
    # optional enrich if keys exist
    for old, new in [
        (
            'aiAssetAnalysis.copilot.quickPrompts.czsc":"Review Chan/CZSC structure for {symbol}: timeframe, zhongshu, buy/sell points, invalidation."',
            'aiAssetAnalysis.copilot.quickPrompts.czsc":"Review Chan/CZSC for {symbol}: bi/duan/zhongshu and BS points; optional 30m+5m multilevel; invalidation and wait-or-act. Prefer system CZSC."',
        ),
        (
            'aiAssetAnalysis.copilot.quickPrompts.chan_short":"Design a short-term Chan or 5m Bollinger strategy for {symbol} following four_way signals."',
            'aiAssetAnalysis.copilot.quickPrompts.chan_short":"Design a short-term strategy for {symbol}: prefer class 1/2/3 Chan BS or zhongshu entries; clear trend may use 5m Bollinger; four_way + exit_owner/flip_mode + backtest steps."',
        ),
    ]:
        if old in text or new.split('":"', 1)[0] in text:
            reps.append((old, new))
    return _patch_file(path, reps)


def main() -> int:
    total = patch_zh_cn() + patch_chip_bundle() + patch_en_index()
    print(f"total replacements: {total}")
    # verify
    js = (ASSETS / "index-CQcKXJTG.js").read_text(encoding="utf-8")
    zh = (ASSETS / "zh-CN-9JXFFF04.js").read_text(encoding="utf-8")
    print("verify js czsc-structure", 'key:"czsc-structure"' in js)
    print("verify js title bind", "strategyExampleCzscStructure" in js)
    print("verify zh titles", zh.count("strategyExampleCzscStructure"))
    print("verify zh prompts", zh.count("strategyExamples.czscStructure"))
    return 0 if 'key:"czsc-structure"' in js and "strategyExampleCzscStructure" in zh else 1


if __name__ == "__main__":
    sys.exit(main())
