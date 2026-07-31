# -*- coding: utf-8 -*-
"""Verify local + live ChanQuant FE 开发教程 wiring after cq1 cache-bust deploy.

Bases:
  - http://127.0.0.1:8888  (local compose)
  - http://121.199.15.56   (live ChanQuant FE :80 — co-hosted; /health returns OK)

Notes (AGENTS.md inventory):
  - ChanQuant SSH target is 220.167.103.213:10043 with FE on 127.0.0.1:8888.
  - From this network, public http://220.167.103.213 often returns carrier/WAF 404
    and SSH :10043 is flaky; do NOT treat OpenIM-only paths as ChanQuant FE.
  - Public :8888 on Aliyun is not the documented external surface (binds localhost).
"""
from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CHECKS: list[tuple[str, bool]] = []

BASES = (
    "http://127.0.0.1:8888",
    "http://121.199.15.56",
)


def _get(url: str, timeout: float = 20) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return int(resp.status), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace") if e.fp else ""
        return int(e.code), body


def check(base: str) -> None:
    print("BASE", base)
    base = base.rstrip("/")

    code, t = _get(base + "/docs/dev-guide-cn.html")
    hs = re.findall(r"<h2[^>]*>(.*?)</h2>", t) if code == 200 else []
    ok_docs = (
        code == 200
        and len(hs) == 7
        and "共 7 节" in t
        and not re.search(r"quantdinger|QuantDinger", t, re.I)
    )
    print("  docs-cn", code, "h2", len(hs), "toc7", "共 7 节" in t)
    CHECKS.append((base + " docs-cn", ok_docs))

    code_en, t_en = _get(base + "/docs/dev-guide.html")
    ok_en = code_en == 200 and ("<h2" in t_en or "ChanQuant" in t_en or "dev" in t_en.lower())
    print("  docs-en", code_en, "ok", ok_en)
    CHECKS.append((base + " docs-en", ok_en))

    code_js, js = _get(base + "/assets/index-DvAGmmZH-cq1.js")
    body = re.search(r"openDevGuide\(\)\{.*?\}(?=,open)", js) if code_js == 200 else None
    snippet = body.group(0) if body else "MISS"
    if len(snippet) > 120:
        snippet = snippet[:120] + "..."
    print("  openDevGuide", snippet)
    ok_js = (
        code_js == 200
        and body is not None
        and "/docs/dev-guide-cn.html?from=ide" in body.group(0)
        and "if(!w)" in body.group(0)
        and "STRATEGY_DEV_GUIDE" not in js
        and "github.com/brokermr810/ChanQuant/blob" not in js
        and "ide-guide-link" in js
    )
    CHECKS.append((base + " ide-js", ok_js))

    # strategy-directives must be locale-aware (not CN-hardcoded)
    dir_body = re.search(r"openStrategyDirectivesDocs\(\)\{.*?\}(?=,)", js) if code_js == 200 else None
    ok_dir = (
        dir_body is not None
        and "$i18n" in dir_body.group(0)
        and "/docs/dev-guide.html?from=ide" in dir_body.group(0)
        and "#contract" in dir_body.group(0)
        and 'const i="/docs/dev-guide-cn.html' not in dir_body.group(0)
    )
    print("  directives locale", ok_dir)
    CHECKS.append((base + " directives-locale", ok_dir))

    code_old, _ = _get(base + "/assets/index-DvAGmmZH.js", timeout=10)
    old_404 = code_old == 404
    print("  old leaf 404", old_404, "status", code_old)
    CHECKS.append((base + " old-leaf-404", old_404))

    for old_name in ("index-Bv_zhOcS.js", "index-CpKYkjon.js"):
        c, _ = _get(base + f"/assets/{old_name}", timeout=10)
        ok = c == 404
        print(f"  old {old_name} 404", ok, "status", c)
        CHECKS.append((base + f" old-{old_name}-404", ok))

    code_main, main = _get(base + "/assets/index-Bv_zhOcS-cq1.js")
    stale_leaf = "index-DvAGmmZH.js" in main.replace("index-DvAGmmZH-cq1.js", "X")
    ok_imp = (
        code_main == 200
        and "DvAGmmZH-cq1" in main
        and "CpKYkjon-cq1" in main
        and not stale_leaf
    )
    print(
        "  entry cq1",
        code_main,
        "leaf",
        "DvAGmmZH-cq1" in main,
        "parent",
        "CpKYkjon-cq1" in main,
        "stale",
        stale_leaf,
    )
    CHECKS.append((base + " entry-importer", ok_imp))

    code_html, html = _get(base + "/index.html")
    html_wo = html.replace("index-Bv_zhOcS-cq1.js", "X")
    ok_html = code_html == 200 and "index-Bv_zhOcS-cq1.js" in html and "index-Bv_zhOcS.js" not in html_wo
    print("  index.html entry", ok_html)
    CHECKS.append((base + " index-html", ok_html))

    code_cp, cp = _get(base + "/assets/index-CpKYkjon-cq1.js")
    ok_cp = code_cp == 200 and "DvAGmmZH-cq1" in cp
    print("  CpKY cq1", code_cp, ok_cp)
    CHECKS.append((base + " cpky-importer", ok_cp))
    print()


for b in BASES:
    try:
        check(b)
    except Exception as e:
        print("FAIL", b, type(e).__name__, e)
        CHECKS.append((b, False))

print("=== SUMMARY ===")
all_ok = True
for name, ok in CHECKS:
    print(("OK" if ok else "BAD"), name)
    all_ok = all_ok and ok
sys.exit(0 if all_ok else 1)
