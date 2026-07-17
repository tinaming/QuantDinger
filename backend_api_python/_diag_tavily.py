"""Diagnostic: trace why Tavily search may not fire during AI chat."""
import sys, os, json, time
sys.path.insert(0, "/app")

print("=" * 60)
print("[DIAG-1] Check TAVILY_API_KEYS env var")
print("=" * 60)
raw = os.getenv("TAVILY_API_KEYS", "")
print(f"  TAVILY_API_KEYS env = '{raw[:20]}...' (len={len(raw)})")

print("\n[DIAG-2] Check APIKeys config loader")
from app.config import APIKeys
keys = APIKeys.TAVILY_API_KEYS
print(f"  APIKeys.TAVILY_API_KEYS = {len(keys)} key(s): {[k[:12]+'...' for k in keys]}")

print("\n[DIAG-3] Check SearchService provider init")
from app.services.search import get_search_service, reset_search_service
reset_search_service()
svc = get_search_service()
statuses = svc.provider_status()
for s in statuses:
    flag = "OK" if s["available"] else ("CFG" if s["configured"] else "--")
    print(f"  [{flag}] {s['provider']:14s} configured={s['configured']} registered={s['registered']} available={s['available']} | {s.get('note','')}")

print("\n[DIAG-4] Test actual Tavily search call")
t0 = time.perf_counter()
try:
    results = svc.search("贵州茅台 最新新闻", num_results=3, days=14)
    elapsed = time.perf_counter() - t0
    print(f"  search returned {len(results)} results in {elapsed:.1f}s")
    for i, r in enumerate(results[:3], 1):
        print(f"    {i}. {r.get('title','?')[:60]}")
        print(f"       {r.get('url','?')[:80]}")
except Exception as e:
    elapsed = time.perf_counter() - t0
    print(f"  search FAILED after {elapsed:.1f}s: {e}")

print("\n[DIAG-5] Check tavily-python import")
try:
    from tavily import TavilyClient
    print("  tavily-python: INSTALLED")
except ImportError:
    print("  tavily-python: NOT INSTALLED (will use REST fallback)")

print("\n[DIAG-6] Simulate _research_task_flags for '茅台相关新闻'")
from app.routes.ai_chat import _research_task_flags, _needs_intelligence_context, _build_research_context

test_msgs = [
    ("茅台相关新闻", "market_analysis"),
    ("茅台相关新闻", "general"),
    ("茅台相关新闻", ""),
    ("搜索茅台", "market_analysis"),
    ("搜索茅台", "general"),
    ("搜索茅台", ""),
    ("茅台最新价格走势", "market_analysis"),
    ("贵州茅台 2025年报", "market_analysis"),
]
for msg, intent in test_msgs:
    flags = _research_task_flags(msg, intent)
    needs_ic = _needs_intelligence_context(msg, intent)
    any_flags = any(flags.values())
    gate_pass = needs_ic or any_flags
    will_search = flags["needs_news"] or flags["needs_fundamentals"] or (flags["needs_market_data"] and not [])
    print(f"  msg='{msg}' intent='{intent}'")
    print(f"    needs_news={flags['needs_news']} needs_market_data={flags['needs_market_data']} needs_macro={flags['needs_macro']}")
    print(f"    _needs_intelligence_context={needs_ic} any(flags)={any_flags} GATE_PASS={gate_pass}")
    print(f"    → will_call_search={will_search}")

print("\n[DIAG-7] Full _build_research_context simulation")
for msg, intent in [("茅台相关新闻", "general"), ("搜索茅台", "general")]:
    ctx = {"user_message": msg, "intent": intent, "language": "zh-CN"}
    t0 = time.perf_counter()
    try:
        result = _build_research_context(ctx)
        elapsed = time.perf_counter() - t0
        news = result.get("news", {})
        web = news.get("web_results", [])
        print(f"  msg='{msg}' intent='{intent}' → {len(web)} web results in {elapsed:.1f}s")
        if result:
            print(f"    keys: {list(result.keys())}")
            print(f"    data_gaps: {result.get('data_gaps', [])}")
        else:
            print(f"    EMPTY research context!")
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"  msg='{msg}' intent='{intent}' → FAILED in {elapsed:.1f}s: {e}")

print("\n" + "=" * 60)
print("DIAGNOSTIC COMPLETE")
print("=" * 60)
