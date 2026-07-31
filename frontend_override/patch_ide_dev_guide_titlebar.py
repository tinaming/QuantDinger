# -*- coding: utf-8 -*-
"""Ensure 「开发教程」is visible in the Indicator IDE title bar (not only when code panel expanded)."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from _ide_chunk import resolve_ide_chunk  # noqa: E402

# Insert always-visible link just before the collapse chevron in panel title.
OLD = (
    't("a-icon",{staticClass:"panel-title-chevron",attrs:{type:e.codePanelExpanded?"up":"down"}})'
)

NEW = (
    't("a",{staticClass:"ide-guide-link ide-guide-link--title",'
    'attrs:{href:"/docs/dev-guide-cn.html?from=ide",target:"_blank",rel:"noopener noreferrer",'
    'title:e.$t("indicatorIde.devGuideTooltip")},'
    "on:{click:function(a){a.preventDefault();a.stopPropagation();e.openDevGuide&&e.openDevGuide()}}},"
    '[e._v(" "+e._s(e.$t("indicatorIde.devGuide"))+" ")],1),'
    + OLD
)

MARKER = "ide-guide-link--title"


def main() -> int:
    target = resolve_ide_chunk()
    if target is None:
        print("missing IDE bundle with ide-guide-link")
        return 1
    text = target.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if MARKER in text:
        print(f"title-bar guide link already present ({target.name})")
        return 0
    if OLD not in text:
        print("MISS panel-title-chevron")
        return 1
    # Only first occurrence in IDE code panel title
    text = text.replace(OLD, NEW, 1)
    target.write_bytes(text.encode("utf-8"))
    print(f"wrote {target.name}: title-bar 开发教程 link")
    return 0


if __name__ == "__main__":
    sys.exit(main())
