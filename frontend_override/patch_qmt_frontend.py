#!/usr/bin/env python3
"""Surgical QMT enablement patches for frontend_override built SPA assets.

ChanQuant-Vue source is not in this workspace; the branded image is an overlay
of prebuilt JS. This script patches the minified bundles so CNStock can go
live via QMT the same way USStock uses IBKR/Alpaca.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
ASSETS = ROOT / "html" / "assets"


def _patch_file(path: pathlib.Path, replacements: list[tuple[str, str]]) -> int:
    text = path.read_text(encoding="utf-8")
    changed = 0
    for old, new in replacements:
        count = text.count(old)
        if count == 0:
            print(f"  MISS  {path.name}: {old[:80]!r}")
            continue
        text = text.replace(old, new)
        changed += count
        print(f"  OK    {path.name}: {count}x {old[:60]!r}")
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def patch_broker_panel() -> int:
    path = ASSETS / "index-CBCO4rly.js"
    if not path.exists():
        print(f"missing {path}")
        return 0

    old_map = (
        'const A={ibkr:{status:"/api/ibkr/status",connect:"/api/ibkr/connect",'
        'disconnect:"/api/ibkr/disconnect",account:"/api/ibkr/account",'
        'positions:"/api/ibkr/positions",orders:"/api/ibkr/orders",'
        'order:"/api/ibkr/order",quote:"/api/ibkr/quote"},'
        'alpaca:{status:"/api/alpaca/status",connect:"/api/alpaca/connect",'
        'disconnect:"/api/alpaca/disconnect",account:"/api/alpaca/account",'
        'positions:"/api/alpaca/positions",orders:"/api/alpaca/orders",'
        'order:"/api/alpaca/order",quote:"/api/alpaca/quote"}};'
    )
    new_map = (
        'const A={ibkr:{status:"/api/ibkr/status",connect:"/api/ibkr/connect",'
        'disconnect:"/api/ibkr/disconnect",account:"/api/ibkr/account",'
        'positions:"/api/ibkr/positions",orders:"/api/ibkr/orders",'
        'order:"/api/ibkr/order",quote:"/api/ibkr/quote"},'
        'alpaca:{status:"/api/alpaca/status",connect:"/api/alpaca/connect",'
        'disconnect:"/api/alpaca/disconnect",account:"/api/alpaca/account",'
        'positions:"/api/alpaca/positions",orders:"/api/alpaca/orders",'
        'order:"/api/alpaca/order",quote:"/api/alpaca/quote"},'
        'qmt:{status:"/api/qmt/status",connect:"/api/qmt/connect",'
        'disconnect:"/api/qmt/disconnect",account:"/api/qmt/account",'
        'positions:"/api/qmt/positions",orders:"/api/qmt/orders",'
        'order:"/api/qmt/order",quote:"/api/qmt/quote"}};'
    )

    return _patch_file(path, [
        (old_map, new_map),
        ('const c={ibkr:u("ibkr"),alpaca:u("alpaca")}', 'const c={ibkr:u("ibkr"),alpaca:u("alpaca"),qmt:u("qmt")}'),
        ('h=["alpaca","ibkr"]', 'h=["alpaca","ibkr","qmt"]'),
        (
            'm={alpaca:{id:"alpaca",icon:"thunderbolt",color:"#1890ff",accent:"#722ed1",markets:["USStock","Crypto"],badges:["zero_commission","rest_api"],cloudFriendly:!0},ibkr:{id:"ibkr",icon:"global",color:"#fa8c16",accent:"#d4380d",markets:["USStock","Forex","Futures"],badges:["tws_required","pro_features"],cloudFriendly:!1}}',
            'm={alpaca:{id:"alpaca",icon:"thunderbolt",color:"#1890ff",accent:"#722ed1",markets:["USStock","Crypto"],badges:["zero_commission","rest_api"],cloudFriendly:!0},ibkr:{id:"ibkr",icon:"global",color:"#fa8c16",accent:"#d4380d",markets:["USStock","Forex","Futures"],badges:["tws_required","pro_features"],cloudFriendly:!1},qmt:{id:"qmt",icon:"stock",color:"#52c41a",accent:"#389e0d",markets:["CNStock"],badges:["miniqmt_required","long_only","lot_100"],cloudFriendly:!1}}',
        ),
        (
            'st={alpaca:"AlpacaConnectForm",ibkr:"IbkrConnectForm"}',
            'st={alpaca:"AlpacaConnectForm",ibkr:"IbkrConnectForm",qmt:"IbkrConnectForm"}',
        ),
        (
            'at={alpaca:"https://app.alpaca.markets/paper/dashboard/overview",ibkr:"https://www.interactivebrokers.com/en/trading/tws.php"}',
            'at={alpaca:"https://app.alpaca.markets/paper/dashboard/overview",ibkr:"https://www.interactivebrokers.com/en/trading/tws.php",qmt:"https://dict.thinktrader.net/nativeApi/start_now.html"}',
        ),
        # KPI: treat qmt like cash/total_asset account
        (
            'return this.brokerId==="alpaca"?[{key:"equity",label:this.$t("brokerAccounts.kpi.equity"),value:i(s.equity||s.portfolio_value,t)}',
            'return this.brokerId==="qmt"?[{key:"equity",label:this.$t("brokerAccounts.kpi.equity")||"总资产",value:i(s.total_asset||s.equity,t)},{key:"cash",label:this.$t("brokerAccounts.kpi.cash")||"可用资金",value:i(s.cash||s.total_cash_value,t)},{key:"mv",label:"持仓市值",value:i(s.market_value,t),tone:"accent"},{key:"frozen",label:"冻结资金",value:i(s.frozen_cash,t)}]:this.brokerId==="alpaca"?[{key:"equity",label:this.$t("brokerAccounts.kpi.equity"),value:i(s.equity||s.portfolio_value,t)}',
        ),
    ])


def patch_trading_assistant() -> int:
    path = ASSETS / "index-DDl85Ivm.js"
    if not path.exists():
        print(f"missing {path}")
        return 0

    reps: list[tuple[str, str]] = [
        (
            'isIBKRMarket(){return this.selectedMarketCategory==="USStock"}',
            'isIBKRMarket(){return this.selectedMarketCategory==="USStock"},isQMTMarket(){return this.selectedMarketCategory==="CNStock"}',
        ),
        (
            'isBrokerMarket(){return this.isIBKRMarket}',
            'isBrokerMarket(){return this.isIBKRMarket||this.isQMTMarket}',
        ),
        (
            '!["Crypto","USStock"].includes(this.selectedMarketCategory)',
            '!["Crypto","USStock","CNStock"].includes(this.selectedMarketCategory)',
        ),
        (
            '["Crypto","USStock"].includes(this.selectedMarketCategory)',
            '["Crypto","USStock","CNStock"].includes(this.selectedMarketCategory)',
        ),
        (
            's==="USStock"?this.currentBrokerId==="ibkr"||t==="ibkr"||t==="alpaca":!1',
            's==="USStock"?this.currentBrokerId==="ibkr"||t==="ibkr"||t==="alpaca":s==="CNStock"?this.currentBrokerId==="qmt"||t==="qmt":!1',
        ),
        (
            'Pt=[{value:"ibkr",labelKey:"ibkr",name:"Interactive Brokers"}]',
            'Pt=[{value:"ibkr",labelKey:"ibkr",name:"Interactive Brokers"},{value:"qmt",labelKey:"qmt",name:"QMT (miniQMT A-Shares)"}]',
        ),
        (
            'getMarketColor(s){return{USStock:"green",Crypto:"purple",Forex:"gold",Futures:"cyan"}[s]||"default"}',
            'getMarketColor(s){return{USStock:"green",CNStock:"green",Crypto:"purple",Forex:"gold",Futures:"cyan"}[s]||"default"}',
        ),
        (
            'this.selectedMarketCategory==="USStock"){this.currentBrokerId="ibkr";try{this.form&&this.form.setFieldsValue&&this.form.setFieldsValue({broker_id:"ibkr"})}catch{}}',
            'this.selectedMarketCategory==="USStock"){this.currentBrokerId="ibkr";try{this.form&&this.form.setFieldsValue&&this.form.setFieldsValue({broker_id:"ibkr"})}catch{}}if(this.selectedMarketCategory==="CNStock"){this.currentBrokerId="qmt";try{this.form&&this.form.setFieldsValue&&this.form.setFieldsValue({broker_id:"qmt",trade_direction:"long",market_type:"spot"})}catch{}}',
        ),
        (
            'e==="ibkr"||e==="alpaca")try{const i=this.form&&this.form.getFieldValue&&this.form.getFieldValue("trade_direction");i&&String(i).',
            'e==="ibkr"||e==="alpaca"||e==="qmt")try{const i=this.form&&this.form.getFieldValue&&this.form.getFieldValue("trade_direction");i&&String(i).',
        ),
        (
            '"IBKR / Alpaca currently support long-only trading. Direction locked to Long."',
            '"IBKR / Alpaca / QMT currently support long-only trading. Direction locked to Long."',
        ),
        (
            '"IBKR / Alpaca currently support long-only trading. Direction set to Long."',
            '"IBKR / Alpaca / QMT currently support long-only trading. Direction set to Long."',
        ),
        # Build exchange_config for QMT like IBKR (no credential vault required)
        (
            'isIBKRMarket?{exchange_id:s.broker_id||this.currentBrokerId||"ibkr",ibkr_host:s.ibkr_host||"127.0.0.1",ibkr_port:s.ibkr_port||7497,ibkr_client_id:s.ibkr_client_id||1,ibkr_account:s.ibkr_account||""}:{credential_id:s.credential_id,exchange_id:this.currentExchangeId||void 0}',
            'isQMTMarket?{exchange_id:s.broker_id||this.currentBrokerId||"qmt",qmt_account_id:s.qmt_account_id||s.ibkr_account||"",qmt_path:s.qmt_path||"",qmt_lib_path:s.qmt_lib_path||"",qmt_session_id:s.qmt_session_id||123456}:isIBKRMarket?{exchange_id:s.broker_id||this.currentBrokerId||"ibkr",ibkr_host:s.ibkr_host||"127.0.0.1",ibkr_port:s.ibkr_port||7497,ibkr_client_id:s.ibkr_client_id||1,ibkr_account:s.ibkr_account||""}:{credential_id:s.credential_id,exchange_id:this.currentExchangeId||void 0}',
        ),
        (
            'o=["Crypto","USStock"].includes(this.selectedMarketCategory),c=this.selectedMarketCategory==="USStock"',
            'o=["Crypto","USStock","CNStock"].includes(this.selectedMarketCategory),c=this.selectedMarketCategory==="USStock"||this.selectedMarketCategory==="CNStock"',
        ),
        # When editing a live CNStock strategy, restore broker_id=qmt.
        # NOTE: opens `if(c){` — the closing `}` is added by the follow-up
        # replacement below (`});else{` -> `})}else{`). Both must apply
        # together or the chunk breaks with `SyntaxError: Unexpected token else`.
        (
            'if(n&&o)if(c)this.currentBrokerId=r||"ibkr",this.form.setFieldsValue({broker_id:r||"ibkr",ibkr_host:s.exchange_config.ibkr_host||"127.0.0.1",ibkr_port:s.exchange_config.ibkr_port||7497,ibkr_client_id:s.exchange_config.ibkr_client_id||1,ibkr_account:',
            'if(n&&o)if(c){if(this.selectedMarketCategory==="CNStock"){this.currentBrokerId=r||"qmt";try{this.form.setFieldsValue({broker_id:r||"qmt",trade_direction:"long",market_type:"spot",ibkr_account:(s.exchange_config.qmt_account_id||"")})}catch{}}else this.currentBrokerId=r||"ibkr",this.form.setFieldsValue({broker_id:r||"ibkr",ibkr_host:s.exchange_config.ibkr_host||"127.0.0.1",ibkr_port:s.exchange_config.ibkr_port||7497,ibkr_client_id:s.exchange_config.ibkr_client_id||1,ibkr_account:',
        ),
        # Close the `if(c){` block opened above (replace `;` with `}` before
        # the outer else). Without this the whole /strategy-live chunk fails
        # to parse and the strategy create form never renders.
        (
            'ibkr_account:s.exchange_config.ibkr_account||""});else{',
            'ibkr_account:s.exchange_config.ibkr_account||""})}else{',
        ),
    ]
    return _patch_file(path, reps)


def patch_exchange_modal() -> int:
    path = ASSETS / "ExchangeAccountModal-Casxk9cc.js"
    if not path.exists():
        print(f"missing {path}")
        return 0
    return _patch_file(path, [
        (
            'alpaca:"Alpaca"}[t]||t}',
            'alpaca:"Alpaca",qmt:"QMT (miniQMT)"}[t]||t}',
        ),
        (
            't==="alpaca"?this.addExchangeType="alpaca":t==="ibkr"?this.addExchangeType="ibkr":this.addExchangeType=""',
            't==="alpaca"?this.addExchangeType="alpaca":t==="ibkr"?this.addExchangeType="ibkr":t==="qmt"?this.addExchangeType="qmt":this.addExchangeType=""',
        ),
        (
            'this.addExchangeType==="alpaca"?t.push("api_key","secret_key","base_url"):this.addExchangeType==="ibkr"&&t.push("ibkr_host","ibkr_port","ibkr_client_id"),t}',
            'this.addExchangeType==="alpaca"?t.push("api_key","secret_key","base_url"):this.addExchangeType==="ibkr"?t.push("ibkr_host","ibkr_port","ibkr_client_id"):this.addExchangeType==="qmt"&&t.push("qmt_account_id"),t}',
        ),
        (
            'return this.addExchangeType==="alpaca"?["exchange_id","api_key","secret_key","base_url"]:this.addExchangeType==="ibkr"?["exchange_id","ibkr_host","ibkr_port","ibkr_client_id"]:["exchange_id"]}',
            'return this.addExchangeType==="alpaca"?["exchange_id","api_key","secret_key","base_url"]:this.addExchangeType==="ibkr"?["exchange_id","ibkr_host","ibkr_port","ibkr_client_id"]:this.addExchangeType==="qmt"?["exchange_id","qmt_account_id"]:["exchange_id"]}',
        ),
        (
            'a("a-select-opt-group",{attrs:{label:e.$t("profile.exchange.typeIBKR")}},[a("a-select-option",{attrs:{value:"ibkr"}},[e._v(" Interactive Brokers (IBKR) ")])],1)',
            'a("a-select-opt-group",{attrs:{label:e.$t("profile.exchange.typeIBKR")}},[a("a-select-option",{attrs:{value:"ibkr"}},[e._v(" Interactive Brokers (IBKR) ")])],1),a("a-select-opt-group",{attrs:{label:"QMT / A-Shares"}},[a("a-select-option",{attrs:{value:"qmt"}},[e._v(" QMT (miniQMT A股) ")])],1)',
        ),
    ])


def patch_dashboard_ranking_click() -> int:
    """Make SPA dashboard strategy ranking cards navigate to strategy detail."""
    path = ASSETS / "index-BwghvPsI.js"
    if not path.exists():
        print(f"missing {path}")
        return 0
    return _patch_file(path, [
        (
            'goToStrategyCreate(){this.$router.push({path:"/strategy-live",query:{tab:"strategy",mode:"create"}}).catch(()=>{})},async fetchData(){',
            'goToStrategyCreate(){this.$router.push({path:"/strategy-live",query:{tab:"strategy",mode:"create"}}).catch(()=>{})},'
            'goToRankedStrategy(s){const t=s&&s.strategy_id;if(!t)return;'
            'this.$router.push({path:"/strategy-live",query:{tab:"strategy",strategy_id:String(t)}}).catch(()=>{})},'
            'async fetchData(){',
        ),
        (
            'return a("div",{key:e.strategy_id,staticClass:"ranking-card",class:{"rank-top":r<3}},[',
            'return a("div",{key:e.strategy_id,staticClass:"ranking-card",class:{"rank-top":r<3},'
            'style:{cursor:"pointer"},'
            'attrs:{title:t.$t("dashboard.strategyRanking")||"策略排行榜"},'
            'on:{click:function(){return t.goToRankedStrategy(e)}}},[',
        ),
    ])


def main() -> int:
    print(f"Patching assets under {ASSETS}")
    total = 0
    total += patch_broker_panel()
    total += patch_trading_assistant()
    total += patch_exchange_modal()
    total += patch_dashboard_ranking_click()
    # Verify qmt string present
    hits = 0
    for p in ASSETS.glob("*.js"):
        try:
            if "qmt" in p.read_text(encoding="utf-8", errors="ignore").lower():
                hits += 1
                print(f"  HAS qmt: {p.name}")
        except Exception:
            pass
    print(f"Done. replacements={total}, files_with_qmt={hits}")
    return 0 if total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
