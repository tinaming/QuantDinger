# -*- coding: utf-8 -*-
"""Resolve the live Indicator IDE SPA chunk under html/assets (cache-busted names)."""
from __future__ import annotations

import pathlib

ASSETS = pathlib.Path(__file__).resolve().parent / "html" / "assets"

# Prefer newest cache-bust suffix; fall back to upstream hash name.
KNOWN_IDE_CANDIDATES = (
    ASSETS / "index-DvAGmmZH-cq1.js",
    ASSETS / "index-DvAGmmZH.js",
)

MARKER = "ide-guide-link"


def resolve_ide_chunk(assets: pathlib.Path | None = None) -> pathlib.Path | None:
    """Return the IDE bundle path that contains ide-guide-link, or None."""
    root = assets or ASSETS
    known = (
        root / "index-DvAGmmZH-cq1.js",
        root / "index-DvAGmmZH.js",
    )
    for p in known:
        if p.is_file():
            try:
                if MARKER in p.read_text(encoding="utf-8", errors="ignore"):
                    return p
            except OSError:
                continue
    for p in sorted(root.glob("index-*.js"), key=lambda x: -x.stat().st_size):
        try:
            if MARKER in p.read_text(encoding="utf-8", errors="ignore"):
                return p
        except OSError:
            continue
    return None


def resolve_main_entry(assets: pathlib.Path | None = None) -> pathlib.Path | None:
    """Return cache-busted main entry if present, else upstream hash name."""
    root = assets or ASSETS
    for name in ("index-Bv_zhOcS-cq1.js", "index-Bv_zhOcS.js"):
        p = root / name
        if p.is_file():
            return p
    return None
