# -*- coding: utf-8 -*-
"""Wire Indicator IDE 「开发教程」/ Dev Guide to local /docs/ pages (locale-aware).

Why local (not GitHub):
  Previous patch opened github.com/.../STRATEGY_DEV_GUIDE*.md which is often
  blocked, private, or popup-filtered — so after refresh the link looked broken.
  Durable fix: serve brand-neutral HTML under frontend_override/html/docs/ and
  point the IDE anchor at /docs/dev-guide[-cn].html.

Re-run after replacing index-*.js from upstream:
  python frontend_override/patch_ide_dev_guide_link.py
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from _ide_chunk import resolve_ide_chunk  # noqa: E402

DOC_CN = "/docs/dev-guide-cn.html?from=ide"
DOC_EN = "/docs/dev-guide.html?from=ide"

NEW_LINK = (
    't("a",{staticClass:"ide-guide-link",attrs:{href:"'
    + DOC_CN
    + '",target:"_blank",'
    'rel:"noopener noreferrer"},'
    "on:{click:function(a){a.preventDefault();a.stopPropagation();e.openDevGuide&&e.openDevGuide()}}},"
    '[e._v(" "+e._s(e.$t("indicatorIde.devGuide"))+" "),t("a-icon",{attrs:{type:"arrow-right"}})],1)'
)

NEW_METHOD = (
    'openDevGuide(){const i=((this.$i18n&&this.$i18n.locale)||"").toLowerCase();'
    f'const e=i.startsWith("zh")?"{DOC_CN}":"{DOC_EN}";'
    'const w=window.open(e,"_blank","noopener");'
    "if(!w){window.location.assign(e)}}"
)

NEW_DIRECTIVES = (
    'openStrategyDirectivesDocs(){const i=((this.$i18n&&this.$i18n.locale)||"").toLowerCase();'
    f'const e=(i.startsWith("zh")?"{DOC_CN}":"{DOC_EN}")+"#contract";'
    'const w=window.open(e,"_blank","noopener");'
    "if(!w){window.location.assign(e)}}"
)

ALREADY = f'openDevGuide(){{const i=((this.$i18n&&this.$i18n.locale)||"").toLowerCase();const e=i.startsWith("zh")?"{DOC_CN}"'
ALREADY_DIRECTIVES = (
    'openStrategyDirectivesDocs(){const i=((this.$i18n&&this.$i18n.locale)||"").toLowerCase();'
    f'const e=(i.startsWith("zh")?"{DOC_CN}":"{DOC_EN}")+"#contract"'
)


def _write_lf(path: pathlib.Path, text: str) -> None:
    path.write_bytes(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))


def _find_target() -> pathlib.Path | None:
    return resolve_ide_chunk()


def _patch_link(text: str) -> tuple[str, int]:
    if NEW_LINK in text:
        print("link already local")
        return text, 0
    # Replace bar ide-guide-link <a> vnode (not title-bar variant)
    pat = re.compile(
        r't\("a",\{staticClass:"ide-guide-link",attrs:\{href:"[^"]*",target:"_blank",rel:"noopener noreferrer"\},'
        r"on:\{click:function\(a\)\{[^}]*\}\}\},"
        r'\[e\._v\(" "\+e\._s\(e\.\$t\("indicatorIde\.devGuide"\)\)\+" "\),t\("a-icon",\{attrs:\{type:"arrow-right"\}\}\)\],1\)'
    )
    m = pat.search(text)
    if not m:
        print("MISS ide-guide-link")
        return text, -1
    text = text[: m.start()] + NEW_LINK + text[m.end() :]
    print(f"patched ide-guide-link → {DOC_CN}")
    return text, 1


def _patch_open_dev_guide(text: str) -> tuple[str, int]:
    if ALREADY in text and "if(!w)" in text:
        print("openDevGuide already local + hardened")
        return text, 0
    # Match from openDevGuide(){ ... }, up to next method (openStrategyDirectivesDocs or next ident)
    pat = re.compile(r"openDevGuide\(\)\{.*?\}(?=,open[A-Z]|,$)")
    m = pat.search(text)
    if not m:
        # Fallback: known GitHub body
        old_gh = (
            'openDevGuide(){const i=((this.$i18n&&this.$i18n.locale)||"").toLowerCase();'
            'const e=i.startsWith("zh")?'
            '"https://github.com/brokermr810/ChanQuant/blob/main/docs/STRATEGY_DEV_GUIDE_CN.md"'
            ':"https://github.com/brokermr810/ChanQuant/blob/main/docs/STRATEGY_DEV_GUIDE.md";'
            'try{window.open(e,"_blank","noopener")}catch{}}'
        )
        if old_gh in text:
            text = text.replace(old_gh, NEW_METHOD, 1)
            print("patched openDevGuide (exact GitHub body)")
            return text, 1
        print("MISS openDevGuide")
        return text, -1
    text = text[: m.start()] + NEW_METHOD + text[m.end() :]
    print(f"patched openDevGuide → local {DOC_CN}")
    return text, 1


def _patch_directives(text: str) -> tuple[str, int]:
    if ALREADY_DIRECTIVES in text and "if(!w)" in text:
        print("directives already local + locale-aware")
        return text, 0
    pat = re.compile(r"openStrategyDirectivesDocs\(\)\{.*?\}(?=,|$)")
    m = pat.search(text)
    if m:
        text = text[: m.start()] + NEW_DIRECTIVES + text[m.end() :]
        print("patched openStrategyDirectivesDocs → local locale-aware")
        return text, 1
    old = (
        'openStrategyDirectivesDocs(){const i="https://github.com/brokermr810/ChanQuant/blob/main/docs/'
        'STRATEGY_DEV_GUIDE.md#41-fixed-stop-loss-take-profit-and-entry-sizing-in-indicatorstrategy";'
        'try{window.open(i,"_blank","noopener")}catch{}}'
    )
    if old in text:
        text = text.replace(old, NEW_DIRECTIVES, 1)
        print("patched openStrategyDirectivesDocs (exact)")
        return text, 1
    # Upgrade prior CN-only local body
    old_cn = (
        f'openStrategyDirectivesDocs(){{const i="{DOC_CN}#contract";'
        'const w=window.open(i,"_blank","noopener");'
        "if(!w){window.location.assign(i)}}"
    )
    if old_cn in text:
        text = text.replace(old_cn, NEW_DIRECTIVES, 1)
        print("patched openStrategyDirectivesDocs (upgrade CN-only → locale)")
        return text, 1
    print("SKIP openStrategyDirectivesDocs (not found)")
    return text, 0



def main() -> int:
    target = _find_target()
    if target is None:
        print("missing IDE bundle with ide-guide-link")
        return 1
    docs_cn = ROOT / "html" / "docs" / "dev-guide-cn.html"
    docs_en = ROOT / "html" / "docs" / "dev-guide.html"
    if not docs_cn.is_file() or not docs_en.is_file():
        print(f"missing local docs under {ROOT / 'html' / 'docs'}")
        return 1

    text = target.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    changed = 0

    text, n = _patch_link(text)
    if n < 0:
        return 1
    changed += n

    text, n = _patch_open_dev_guide(text)
    if n < 0:
        return 1
    changed += n

    text, n = _patch_directives(text)
    if n < 0:
        return 1
    changed += n

    # Scrub leftover GitHub guide URLs in this bundle
    before = text
    text = text.replace(
        "https://github.com/brokermr810/ChanQuant/blob/main/docs/STRATEGY_DEV_GUIDE_CN.md",
        DOC_CN,
    )
    text = text.replace(
        "https://github.com/brokermr810/ChanQuant/blob/main/docs/STRATEGY_DEV_GUIDE.md",
        DOC_EN,
    )
    # Normalize any bare /docs/dev-guide*.html hrefs (without ?from=ide) in this IDE bundle
    text2 = re.sub(
        r'href:"/docs/dev-guide-cn\.html(?:\?from=ide)?"',
        f'href:"{DOC_CN}"',
        text,
    )
    text2 = re.sub(
        r'href:"/docs/dev-guide\.html(?:\?from=ide)?"',
        f'href:"{DOC_EN}"',
        text2,
    )
    if text2 != before:
        text = text2
        changed += 1
        print("scrubbed/normalized guide URLs")
    else:
        text = text2

    # Always-visible title-bar link (guide bar is inside collapsed code panel)
    title_marker = "ide-guide-link--title"
    if title_marker not in text:
        old_chevron = (
            't("a-icon",{staticClass:"panel-title-chevron",'
            'attrs:{type:e.codePanelExpanded?"up":"down"}})'
        )
        new_title = (
            't("a",{staticClass:"ide-guide-link ide-guide-link--title",'
            f'attrs:{{href:"{DOC_CN}",target:"_blank",rel:"noopener noreferrer",'
            'title:e.$t("indicatorIde.devGuideTooltip")},'
            "on:{click:function(a){a.preventDefault();a.stopPropagation();"
            "e.openDevGuide&&e.openDevGuide()}}},"
            '[e._v(" "+e._s(e.$t("indicatorIde.devGuide"))+" ")],1),'
            + old_chevron
        )
        if old_chevron in text:
            text = text.replace(old_chevron, new_title, 1)
            changed += 1
            print("inserted title-bar 开发教程 link")
        else:
            print("SKIP title-bar chevron (not found)")
    else:
        # Ensure title-bar href is local
        text3, n = re.subn(
            r'(staticClass:"ide-guide-link ide-guide-link--title",attrs:\{href:")[^"]*(")',
            rf"\1{DOC_CN}\2",
            text,
            count=1,
        )
        if n and text3 != text:
            text = text3
            changed += 1
            print("normalized title-bar href")


    if changed:
        _write_lf(target, text)
        print(f"wrote {target.name} ({changed} edits)")
    else:
        print(f"no write needed for {target.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
