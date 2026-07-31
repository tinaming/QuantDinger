#!/usr/bin/env python3
"""Surgical SPA patches for ChanQuant test-record UX/A-share issues.

ChanQuant-Vue source lives in a private sibling repo and is not in this workspace
(see DEVELOPMENT.md). Patch prebuilt assets under frontend_override/html/assets
(same approach as patch_qmt_frontend.py).

Limits of prebuilt-asset patching:
- Can add buttons/inputs wired to existing Vue data/methods.
- Cannot cleanly rebuild components or add TypeScript source.
- Re-apply after replacing SPA assets from a new ChanQuant-frontend image.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
ASSETS = ROOT / "html" / "assets"


def _read_text_lf(path: pathlib.Path) -> str:
    """Read as UTF-8 and normalize physical CRLF/CR to LF (Windows-safe)."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _write_text_lf(path: pathlib.Path, text: str) -> None:
    """Write UTF-8 with LF-only newlines (never CRLF via text-mode translation)."""
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
            # Already applied?
            if new and text.count(new) > 0:
                print(f"  OK    {path.name}: already applied {new[:70]!r}")
                continue
            print(f"  MISS  {path.name}: {old[:90]!r}")
            continue
        if old == new:
            print(f"  SKIP  {path.name}: identical")
            continue
        text = text.replace(old, new)
        changed += count
        print(f"  OK    {path.name}: {count}x {old[:70]!r}")
    if changed or had_cr:
        _write_text_lf(path, text)
        if had_cr and not changed:
            print(f"  OK    {path.name}: normalized CRLF -> LF")
    return changed


def patch_ide_ashare_flash_trade() -> int:
    """Allow opening flash trade for CNStock (not only Crypto)."""
    path = ASSETS / "index-DvAGmmZH.js"
    return _patch_file(path, [
        (
            'toggleQuickTradeDrawer(){if(!this.quickTradeDrawerVisible&&this.market!=="Crypto"){this.$message.warning(this.$t("quickTrade.cryptoOnly"));return}this.quickTradeDrawerVisible=!this.quickTradeDrawerVisible}',
            'toggleQuickTradeDrawer(){if(!this.quickTradeDrawerVisible&&!["Crypto","CNStock"].includes(this.market)){this.$message.warning(this.$t("quickTrade.cryptoOnly"));return}this.quickTradeDrawerVisible=!this.quickTradeDrawerVisible}',
        ),
        (
            'openQuickTrade(){if(this.market!=="Crypto"){this.$message.warning(this.$t("quickTrade.cryptoOnly"));return}this.qtSymbol=this.symbol||""',
            'openQuickTrade(){if(!["Crypto","CNStock"].includes(this.market)){this.$message.warning(this.$t("quickTrade.cryptoOnly"));return}this.qtSymbol=this.symbol||""',
        ),
        (
            'handleQuickTradeSymbolChange(i){i&&this.market==="Crypto"&&(this.qtSymbol=i)}',
            'handleQuickTradeSymbolChange(i){i&&["Crypto","CNStock"].includes(this.market)&&(this.qtSymbol=i)}',
        ),
    ])


def patch_quick_trade_panel_cnstock() -> int:
    """Symbol search/price in QuickTradePanel should respect CNStock."""
    path = ASSETS / "QuickTradePanel-Di3-zL0Q.js"
    return _patch_file(path, [
        (
            'const t=await m({market:"Crypto",keyword:i.trim(),limit:20})',
            'const t=await m({market:this.marketType==="spot"&&/^[0-9]{6}/.test(String(this.currentSymbol||i||"").replace(/\\D/g,""))?"CNStock":(this.panelMarket||this.market||"Crypto"),keyword:i.trim(),limit:20})',
        ),
        (
            'params:{market:"Crypto",symbol:this.currentSymbol}',
            'params:{market:(this.panelMarket||this.market||(/^\\d{6}/.test(String(this.currentSymbol||"").replace(/\\D/g,""))?"CNStock":"Crypto")),symbol:this.currentSymbol}',
        ),
    ])


def patch_copilot_schedule_plus() -> int:
    """Add a + button next to scheduled-analysis refresh to open create modal."""
    path = ASSETS / "index-CQcKXJTG.js"
    return _patch_file(path, [
        (
            's("a-button",{attrs:{size:"small",type:"link",loading:t.loadingMonitors},on:{click:t.loadMonitors}},[s("a-icon",{attrs:{type:"reload"}})],1)],1),t.monitors.length===0?s("div",{staticClass:"empty-mini"},[t._v(t._s(t.text.noMonitors))])',
            's("a-button",{attrs:{size:"small",type:"link",title:t.text.createMonitor||"添加定时任务"},on:{click:function(){return t.openTaskModal(t.context)}}},[s("a-icon",{attrs:{type:"plus"}})],1),s("a-button",{attrs:{size:"small",type:"link",loading:t.loadingMonitors},on:{click:t.loadMonitors}},[s("a-icon",{attrs:{type:"reload"}})],1)],1),t.monitors.length===0?s("div",{staticClass:"empty-mini"},[s("div",[t._v(t._s(t.text.noMonitors))]),s("a-button",{attrs:{type:"link",size:"small",icon:"plus"},style:{marginTop:"6px"},on:{click:function(){return t.openTaskModal(t.context)}}},[t._v(t._s(t.text.createMonitor||"添加定时任务"))])],1)',
        ),
    ])


def patch_i18n_crypto_only_message() -> int:
    """Clarify flash-trade restriction covers crypto + A-share QMT."""
    path = ASSETS / "zh-CN-9JXFFF04.js"
    return _patch_file(path, [
        (
            '"quickTrade.cryptoOnly":"仅支持加密货币"',
            '"quickTrade.cryptoOnly":"仅支持加密货币或 A股(QMT)"',
        ),
    ])


def patch_i18n_publish_pending() -> int:
    """Add missing dashboard.indicator.publish.pending (vue-i18n returns key if absent).

    Old span is unpublish→success so the replacement is idempotent (pending sits between them).
    """
    total = 0
    total += _patch_file(ASSETS / "zh-CN-9JXFFF04.js", [
        (
            '"dashboard.indicator.publish.unpublish":"取消发布","dashboard.indicator.publish.success":"发布成功"',
            '"dashboard.indicator.publish.unpublish":"取消发布","dashboard.indicator.publish.pending":"已提交发布，等待审核","dashboard.indicator.publish.success":"发布成功"',
        ),
    ])
    # English locale bundle (fallback / en UI)
    total += _patch_file(ASSETS / "index-Bv_zhOcS.js", [
        (
            '"dashboard.indicator.publish.unpublish":"Unpublish","dashboard.indicator.publish.success":"Published successfully"',
            '"dashboard.indicator.publish.unpublish":"Unpublish","dashboard.indicator.publish.pending":"Submitted for review","dashboard.indicator.publish.success":"Published successfully"',
        ),
    ])
    return total


def patch_ide_hide_code_handle_title() -> int:
    """Ensure code-side collapse handle is clearly labeled (收起)."""
    path = ASSETS / "index-DvAGmmZH.js"
    return _patch_file(path, [
        (
            't("div",{staticClass:"ide-code-drawer-handle",on:{click:function(a){a.stopPropagation(),e.codeDrawerVisible=!1}}},[t("a-icon",{attrs:{type:"double-left"}}),t("span",[e._v(e._s(e.$t("indicatorIde.hideCode")))])],1)',
            't("div",{staticClass:"ide-code-drawer-handle",attrs:{title:e.$t("indicatorIde.hideCode")||"收起代码"},on:{click:function(a){a.stopPropagation(),e.codeDrawerVisible=!1}}},[t("a-icon",{attrs:{type:"double-left"}}),t("span",[e._v(e._s(e.$t("indicatorIde.hideCode")||"收起"))])],1)',
        ),
    ])


def patch_ide_remove_chart_hide_code_btn() -> int:
    """#7: Hide-code belongs on the code-side drawer handle, not chart toolbar."""
    path = ASSETS / "index-DvAGmmZH.js"
    return _patch_file(path, [
        (
            't("a-tooltip",{attrs:{title:e.codeDrawerVisible?e.$t("indicatorIde.hideCode"):e.$t("indicatorIde.showCode")}},[t("a-button",{staticClass:"chart-panel-icon-btn",attrs:{size:"small",type:e.codeDrawerVisible?"default":"primary"},on:{click:function(a){e.codeDrawerVisible=!e.codeDrawerVisible}}},[t("a-icon",{attrs:{type:"code"}})],1)],1),',
            "",
        ),
    ])


def patch_publish_success_message() -> int:
    """Show pending-review success for community publish."""
    path = ASSETS / "index-DvAGmmZH.js"
    return _patch_file(path, [
        (
            'i&&i.code===1?(this.$message.success(this.$t("dashboard.indicator.publish.success")),this.showPublishModal=!1,this.publishIndicator=null,await this.loadIndicators()):this.$message.error(i&&i.msg||this.$t("dashboard.indicator.publish.failed"))',
            'i&&i.code===1?(this.$message.success(i.msg==="published_pending_review"?(this.$t("dashboard.indicator.publish.pending")||"已提交发布，等待审核"):(this.$t("dashboard.indicator.publish.success")||"发布成功")),this.showPublishModal=!1,this.publishIndicator=null,await this.loadIndicators()):this.$message.error(i&&i.msg||this.$t("dashboard.indicator.publish.failed"))',
        ),
    ])


def patch_ide_cnstock_long_only() -> int:
    """Selecting a CNStock watchlist item forces long-only / 1x leverage in IDE."""
    path = ASSETS / "index-DvAGmmZH.js"
    return _patch_file(path, [
        (
            "e&&(this.market=String(e.market),this.symbol=String(e.symbol),this.qtSymbol=this.symbol)}",
            'e&&(this.market=String(e.market),this.symbol=String(e.symbol),this.qtSymbol=this.symbol,String(e.market)==="CNStock"&&(this.tradeDirection="long",this.leverage=1))}',
        ),
    ])


def patch_ide_symbol_search_button() -> int:
    """#11: Add a visible 搜索 button between watchlist select and timeframe."""
    path = ASSETS / "index-DvAGmmZH.js"
    old = (
        '],2)],1),t("div",{staticClass:"ide-toolbar-group ide-toolbar-group--tf"},'
        '[t("span",{staticClass:"ide-toolbar-label"},[e._v(e._s(e.$t("indicatorIde.toolbar.timeframe")))])'
    )
    new = (
        '],2)],1),t("a-button",{staticClass:"ide-toolbar-search-btn",attrs:{size:"small",type:"default",'
        'title:e.$t("trading-assistant.form.addSymbolTitle")||"搜索标的"},'
        "on:{click:function(){e.showAddModal=!0}}},"
        '[t("a-icon",{attrs:{type:"search"}}),e._v(" 搜索")],1),'
        't("div",{staticClass:"ide-toolbar-group ide-toolbar-group--tf"},'
        '[t("span",{staticClass:"ide-toolbar-label"},[e._v(e._s(e.$t("indicatorIde.toolbar.timeframe")))])'
    )
    return _patch_file(path, [(old, new)])


def patch_ide_editable_indicator_name() -> int:
    """#6: Editable indicator name textbox in the code panel title bar."""
    path = ASSETS / "index-DvAGmmZH.js"
    return _patch_file(path, [
        # data field
        (
            'saveAsName:"",savingAs:!1',
            'saveAsName:"",ideIndicatorNameDraft:"",savingAs:!1',
        ),
        # method + draft sync inside onIndicatorChange
        (
            'onIndicatorChange(i){this.invalidateBacktestMarkersOnContextChange();'
            "const e=this.indicators.find(t=>Number(t.id)===Number(i));"
            'e?(this.currentCode=e.code||"",this.codeDirty=!1,this.cmInstance&&this.cmInstance.setValue(this.currentCode),'
            'this.syncSelectedIndicatorToChart(e.code||""),this.syncTradeUiFromStrategyCode(e.code||"",{silent:!0}))'
            ':(this.currentCode="",this.codeDirty=!1,this.chartVisibleIndicatorIds=[],'
            'this.cmInstance&&this.cmInstance.setValue(""),this.syncSelectedIndicatorToChart()),'
            "this.$nextTick(()=>this.applyCodeMirrorReadOnly())}",
            "applyIdeIndicatorName(){if(!this.selectedIndicatorId||this.selectedIndicatorIsPurchased)return;"
            'const i=(this.ideIndicatorNameDraft||"").trim();'
            'if(!i){this.$message.warning(this.$t("indicatorIde.saveAsNameRequired")||"请输入指标名称");return}'
            "const e=this.selectedIndicatorObj;if(!e||e.name===i)return;e.name=i,this.codeDirty=!0,this.saveIndicator()},"
            "onIndicatorChange(i){this.invalidateBacktestMarkersOnContextChange();"
            "const e=this.indicators.find(t=>Number(t.id)===Number(i));"
            'e?(this.currentCode=e.code||"",this.codeDirty=!1,this.ideIndicatorNameDraft=e.name||"",'
            "this.cmInstance&&this.cmInstance.setValue(this.currentCode),"
            'this.syncSelectedIndicatorToChart(e.code||""),this.syncTradeUiFromStrategyCode(e.code||"",{silent:!0}))'
            ':(this.currentCode="",this.codeDirty=!1,this.ideIndicatorNameDraft="",this.chartVisibleIndicatorIds=[],'
            'this.cmInstance&&this.cmInstance.setValue(""),this.syncSelectedIndicatorToChart()),'
            "this.$nextTick(()=>this.applyCodeMirrorReadOnly())}",
        ),
        # title-bar input (stopPropagation so it does not collapse the panel)
        (
            'staticClass:"panel-title__leading"},[t("a-icon",{attrs:{type:"code"}}),'
            "e.codeDirty&&!e.selectedIndicatorIsPurchased?",
            'staticClass:"panel-title__leading"},[t("a-icon",{attrs:{type:"code"}}),'
            't("a-input",{staticClass:"ide-indicator-name-input",'
            'staticStyle:{width:"220px",marginLeft:"8px"},'
            'attrs:{size:"small",placeholder:e.$t("trading-assistant.detail.indicatorName")||"指标名称",'
            "disabled:!e.selectedIndicatorId||e.selectedIndicatorIsPurchased},"
            "on:{click:function(a){a.stopPropagation()},"
            "pressEnter:function(a){a&&a.stopPropagation&&a.stopPropagation(),e.applyIdeIndicatorName()},"
            "blur:function(){return e.applyIdeIndicatorName()}},"
            "model:{value:e.ideIndicatorNameDraft,callback:function(a){e.ideIndicatorNameDraft=a},"
            'expression:"ideIndicatorNameDraft"}}),'
            "e.codeDirty&&!e.selectedIndicatorIsPurchased?",
        ),
    ])


def patch_ide_collapse_handle_css() -> int:
    """#5: Move 收起 handle onto the vertical code/chart divider (arrow location)."""
    # Prefer the themed IDE css bundle that already defines the handle.
    candidates = sorted(ASSETS.glob("index-*.css"), key=lambda p: -p.stat().st_size)
    path = None
    for c in candidates:
        if "ide-code-drawer-handle" in c.read_text(encoding="utf-8", errors="ignore"):
            path = c
            break
    if path is None:
        print("  MISS  no css with ide-code-drawer-handle")
        return 0

    marker = "/* test-record: collapse handle on divider */"
    extra = (
        f"{marker}"
        ".ide-left[data-v-ec54bf92]{overflow:visible}"
        ".ide-code-drawer-handle[data-v-ec54bf92]{"
        "position:absolute;right:-15px;top:42%;transform:translateY(-50%);"
        "z-index:6;flex-direction:column;writing-mode:vertical-rl;"
        "padding:12px 4px;gap:6px;border:1px solid #e2e8f0;border-left:none;"
        "border-radius:0 8px 8px 0;background:linear-gradient(180deg,#fff,#f1f5f9);"
        "box-shadow:2px 0 8px rgba(15,23,42,.08);color:#475569}"
        ".ide-code-drawer-handle[data-v-ec54bf92]:hover{color:#13C2C2;background:#e8f4ff}"
        ".ide-toolbar-search-btn{margin:0 8px 0 4px;align-self:flex-end}"
        ".ide-indicator-name-input{max-width:240px}"
        ".panel-title__leading{display:flex;align-items:center;gap:4px;min-width:0;flex:1}"
    )
    raw = path.read_bytes()
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    had_cr = b"\r" in raw
    if marker in text:
        if had_cr:
            _write_text_lf(path, text)
            print(f"  OK    {path.name}: collapse CSS already applied (normalized CRLF -> LF)")
        else:
            print(f"  OK    {path.name}: collapse CSS already applied")
        return 0
    _write_text_lf(path, text + extra)
    print(f"  OK    {path.name}: appended collapse/search/name CSS")
    return 1


def main() -> int:
    print(f"Patching assets under {ASSETS}")
    total = 0
    total += patch_ide_ashare_flash_trade()
    total += patch_quick_trade_panel_cnstock()
    total += patch_copilot_schedule_plus()
    total += patch_i18n_crypto_only_message()
    total += patch_i18n_publish_pending()
    total += patch_ide_hide_code_handle_title()
    total += patch_ide_remove_chart_hide_code_btn()
    total += patch_publish_success_message()
    total += patch_ide_cnstock_long_only()
    total += patch_ide_symbol_search_button()
    total += patch_ide_editable_indicator_name()
    total += patch_ide_collapse_handle_css()
    print(f"Done. replacements={total}")
    return 0 if total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
