# -*- coding: utf-8 -*-
"""Update IDE i18n strings for 开发教程 (缠论-first)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from _ide_chunk import resolve_main_entry  # noqa: E402

ASSETS = ROOT / "html" / "assets"


def main() -> int:
    main_entry = resolve_main_entry()
    replacements: list[tuple[Path, list[tuple[str, str]]]] = [
        (
            ASSETS / "zh-CN-9JXFFF04.js",
            [
                (
                    '"indicatorIde.devGuideTooltip":"查看策略/指标代码编写教程"',
                    '"indicatorIde.devGuideTooltip":"缠论优先：预计算 czsc_* 列写法与严格回测"',
                ),
            ],
        ),
    ]
    if main_entry is not None:
        replacements.append(
            (
                main_entry,
                [
                    (
                        '"indicatorIde.devGuideTooltip":"Read the strategy/indicator coding tutorial"',
                        '"indicatorIde.devGuideTooltip":"Chan theory first: czsc_* columns and strict backtest"',
                    ),
                ],
            )
        )
    else:
        print("missing main entry chunk")

    total = 0
    for path, pairs in replacements:
        if not path.exists():
            print(f"missing {path.name}")
            continue
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        changed = 0
        for old, new in pairs:
            if old in text:
                text = text.replace(old, new)
                changed += 1
                print(f"OK {path.name}: tooltip")
            elif new in text:
                print(f"already {path.name}")
            else:
                print(f"MISS {path.name}: {old[:60]!r}")
        if changed:
            path.write_bytes(text.encode("utf-8"))
            total += changed
    print(f"done edits={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
