#!/usr/bin/env python3
"""Patch Copilot for dedicated Chan/trading starters — do NOT overload system-managed skills.

System-managed chips (diagnose / logs / monitor / strategy lab / …) stay as platform control.
Trading/缠论 uses dedicated chips: czsc_analysis + chan_short_strategy, plus Copilot system prompt.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
ASSETS = ROOT / "html" / "assets"
sys.path.insert(0, str(ROOT))
from _ide_chunk import resolve_main_entry  # noqa: E402


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
                print(f"  OK    {path.name}: already applied {new[:60]!r}")
                continue
            print(f"  MISS  {path.name}: {old[:80]!r}")
            continue
        if old == new:
            continue
        text = text.replace(old, new)
        changed += count
        print(f"  OK    {path.name}: {count}x {old[:60]!r}")
    if changed or had_cr:
        _write_text_lf(path, text)
        if had_cr and not changed:
            print(f"  OK    {path.name}: normalized CRLF -> LF")
    return changed


def patch_zh_cn() -> int:
    path = ASSETS / "zh-CN-9JXFFF04.js"
    return _patch_file(path, [
        # Keep welcome inviting Chan questions (not rewriting system skills).
        (
            "可以问行情、让它解释错误日志、写策略模板，或上传 K 线图一起判断。",
            "可以问缠论结构、写短线策略，或在趋势明确时用 5 分钟布林；系统技能（日志/定时/配置）仍用于平台操控。",
        ),
        (
            "可以问缠论结构、写短线策略，或在趋势明确时用 5 分钟布林；也可上传 K 线一起判断。",
            "可以问缠论结构、写短线策略，或在趋势明确时用 5 分钟布林；系统技能（日志/定时/配置）仍用于平台操控。",
        ),
        (
            "例如：帮我诊断 BTC/USDT 1 小时趋势，或者上传 K 线图问它是否适合开仓...",
            "例如：用缠论分析当前标的 30 分钟结构，或写一个 5 分钟短线策略...",
        ),
        # REVERT overloaded system skill starters back to platform wording
        (
            "请用缠论诊断 {symbol}：先定级别，再给分型/笔/中枢、买卖点、失效条件；趋势极明确时可补充 5m 布林思路。",
            "请诊断 {symbol}：趋势、量能、支撑阻力、流动性和风险。",
        ),
        (
            "请为 {symbol} 设计可执行短线策略（优先缠论；趋势明确可用 5m 布林），需符合四路信号与 exit_owner，并给出回测验证步骤。",
            "请为 {symbol} 设计一个可执行的策略研发流程，包括条件、风控和验证计划。",
        ),
        (
            "aiAssetAnalysis.copilot.quickTasks.market_diagnosis.desc\":\"缠论结构优先：级别/中枢/买卖点，并给出风险与失效。",
            "aiAssetAnalysis.copilot.quickTasks.market_diagnosis.desc\":\"趋势、量能、支撑阻力、资金面和风险。",
        ),
        (
            "aiAssetAnalysis.copilot.quickTasks.indicator_strategy.desc\":\"短线策略：缠论或明确趋势（如5m布林），落地 IDE 回测。",
            "aiAssetAnalysis.copilot.quickTasks.indicator_strategy.desc\":\"生成可展示、回测和发布的策略草稿。",
        ),
        # Dedicated trading chip i18n (idempotent)
        (
            "aiAssetAnalysis.copilot.quickTasks.opportunity_radar.desc\":\"筛选未来 24 小时可能触发的机会条件。",
            "aiAssetAnalysis.copilot.quickTasks.opportunity_radar.desc\":\"筛选未来 24 小时可能触发的机会条件。"
            "\",\"aiAssetAnalysis.copilot.quickTasks.czsc_analysis.label\":\"缠论结构\""
            ",\"aiAssetAnalysis.copilot.quickTasks.czsc_analysis.desc\":\"交易分析：分型/笔/中枢与买卖点。\""
            ",\"aiAssetAnalysis.copilot.quickTasks.chan_short_strategy.label\":\"短线策略\""
            ",\"aiAssetAnalysis.copilot.quickTasks.chan_short_strategy.desc\":\"缠论短线，或趋势明确时用 5m 布林。\""
            ",\"aiAssetAnalysis.copilot.quickPrompts.czsc\":\"请对 {symbol} 做缠论结构复盘：明确级别、中枢位置、买卖点（若有）、失效条件与等待/行动建议；优先用系统 CZSC 结果，禁止编造结构。\""
            ",\"aiAssetAnalysis.copilot.quickPrompts.chan_short\":\"请为 {symbol} 写可执行短线策略（优先缠论；趋势明确可用 5m 布林），对齐四路信号与 exit_owner，并给出回测步骤。",
        ),
    ])


def patch_chip_bundle() -> int:
    path = ASSETS / "index-CQcKXJTG.js"
    return _patch_file(path, [
        # Preferred order: keep system skills, add dedicated trading skills after diagnose
        (
            'const s=["market_diagnosis","czsc_analysis","chart_review","indicator_strategy","scheduled_analysis","news_research","debug_logs","macro_economic_data","opportunity_radar"]',
            'const s=["market_diagnosis","czsc_analysis","chan_short_strategy","chart_review","indicator_strategy","scheduled_analysis","news_research","debug_logs","macro_economic_data","opportunity_radar"]',
        ),
        (
            'const s=["market_diagnosis","chart_review","indicator_strategy","scheduled_analysis","news_research","debug_logs","macro_economic_data","opportunity_radar"]',
            'const s=["market_diagnosis","czsc_analysis","chan_short_strategy","chart_review","indicator_strategy","scheduled_analysis","news_research","debug_logs","macro_economic_data","opportunity_radar"]',
        ),
        (
            'market_diagnosis:"diagnose",czsc_analysis:"czsc",chart_review:"chart",indicator_strategy:"strategy",scheduled_analysis:"monitor",monitor_setup:"monitor",debug_logs:"logs",macro_economic_data:"macro",macro_check:"macro",opportunity_radar:"radar"}',
            'market_diagnosis:"diagnose",czsc_analysis:"czsc",chan_short_strategy:"chan_short",chart_review:"chart",indicator_strategy:"strategy",scheduled_analysis:"monitor",monitor_setup:"monitor",debug_logs:"logs",macro_economic_data:"macro",macro_check:"macro",opportunity_radar:"radar"}',
        ),
        (
            'market_diagnosis:"diagnose",chart_review:"chart",indicator_strategy:"strategy",scheduled_analysis:"monitor",monitor_setup:"monitor",debug_logs:"logs",macro_economic_data:"macro",macro_check:"macro",opportunity_radar:"radar"}',
            'market_diagnosis:"diagnose",czsc_analysis:"czsc",chan_short_strategy:"chan_short",chart_review:"chart",indicator_strategy:"strategy",scheduled_analysis:"monitor",monitor_setup:"monitor",debug_logs:"logs",macro_economic_data:"macro",macro_check:"macro",opportunity_radar:"radar"}',
        ),
        # systemQuickTasks fallback chips
        (
            't("czsc","analysis","apartment","indigo","czsc_analysis","czsc_analysis","czsc","Review Chan/CZSC structure for {symbol}: timeframe, zhongshu, buy/sell points, invalidation."),t("chart","chart","picture","purple","chart_review","chart_review","chart",',
            't("czsc","analysis","apartment","indigo","czsc_analysis","czsc_analysis","czsc","Review Chan/CZSC structure for {symbol}: timeframe, zhongshu, buy/sell points, invalidation."),'
            't("chan_short","strategy","thunderbolt","green","chan_short_strategy","chan_short_strategy","chan_short","Design a short-term Chan or 5m Bollinger strategy for {symbol} following four_way signals."),'
            't("chart","chart","picture","purple","chart_review","chart_review","chart",',
        ),
        (
            't("diagnose","analysis","line-chart","blue","market_diagnosis","market_diagnosis","diagnose","Diagnose {symbol}: trend, momentum, support/resistance, liquidity, and risk."),t("chart","chart","picture","purple","chart_review","chart_review","chart",',
            't("diagnose","analysis","line-chart","blue","market_diagnosis","market_diagnosis","diagnose","Diagnose {symbol}: trend, momentum, support/resistance, liquidity, and risk."),'
            't("czsc","analysis","apartment","indigo","czsc_analysis","czsc_analysis","czsc","Review Chan/CZSC structure for {symbol}: timeframe, zhongshu, buy/sell points, invalidation."),'
            't("chan_short","strategy","thunderbolt","green","chan_short_strategy","chan_short_strategy","chan_short","Design a short-term Chan or 5m Bollinger strategy for {symbol} following four_way signals."),'
            't("chart","chart","picture","purple","chart_review","chart_review","chart",',
        ),
        (
            'czsc_analysis:e("czsc_analysis","Chan structure","Review fenxing/bi/zhongshu and buy-sell points."),chart_review:e("chart_review","Chart review",',
            'czsc_analysis:e("czsc_analysis","Chan structure","Trading: fenxing/bi/zhongshu and buy-sell points."),'
            'chan_short_strategy:e("chan_short_strategy","Short-term strategy","Chan short-term or 5m Bollinger when trend is clear."),'
            'chart_review:e("chart_review","Chart review",',
        ),
        (
            'return{market_diagnosis:e("market_diagnosis","Diagnose symbol","Trend, momentum, support/resistance, liquidity, and risk."),chart_review:e("chart_review","Chart review",',
            'return{market_diagnosis:e("market_diagnosis","Diagnose symbol","Trend, momentum, support/resistance, liquidity, and risk."),'
            'czsc_analysis:e("czsc_analysis","Chan structure","Trading: fenxing/bi/zhongshu and buy-sell points."),'
            'chan_short_strategy:e("chan_short_strategy","Short-term strategy","Chan short-term or 5m Bollinger when trend is clear."),'
            'chart_review:e("chart_review","Chart review",',
        ),
    ])


def patch_en_index_soft() -> int:
    """Do not overload English system diagnose/strategy chips; leave if already Chan-overloaded — revert."""
    path = resolve_main_entry()
    if path is None:
        print("missing main entry")
        return 0
    return _patch_file(path, [
        (
            "aiAssetAnalysis.copilot.quickPrompts.diagnose\":\"Diagnose {symbol} with Chan/CZSC: timeframe, structure, buy/sell points, invalidation; if trend is obvious, note a 5m Bollinger alternative.",
            "aiAssetAnalysis.copilot.quickPrompts.diagnose\":\"Diagnose {symbol}: trend, momentum, support/resistance, liquidity, and risk.",
        ),
        (
            "aiAssetAnalysis.copilot.quickPrompts.strategy\":\"Design a short-term strategy for {symbol} (prefer Chan; clear trend may use 5m Bollinger) that follows four_way signals and exit_owner, with backtest steps.",
            "aiAssetAnalysis.copilot.quickPrompts.strategy\":\"Design an executable strategy workflow for {symbol}, including conditions, risk controls, and validation plan.",
        ),
        (
            "aiAssetAnalysis.copilot.quickTasks.market_diagnosis.desc\":\"Chan structure first: timeframe/centers/buy-sell points, plus risk.",
            "aiAssetAnalysis.copilot.quickTasks.market_diagnosis.desc\":\"Trend, momentum, support/resistance, liquidity, and risk.",
        ),
    ])


def main() -> int:
    total = patch_zh_cn() + patch_chip_bundle() + patch_en_index_soft()
    print(f"total replacements: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
