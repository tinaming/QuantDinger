#!/usr/bin/env python3
"""
Export the CoinOS Skills OpenAPI spec as a standalone JSON file.

This generates ``docs/api/coinos-openapi.json`` containing ONLY the
``/api/coinos/*`` endpoints — separate from the main openapi_all.json.

Usage (from backend_api_python/):

    python scripts/export_coinos_openapi.py
    python scripts/export_coinos_openapi.py --output ../docs/api/coinos-openapi.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Repo layout: backend_api_python/scripts/export_coinos_openapi.py
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_ROOT.parent
_DEFAULT_OUTPUT = _REPO_ROOT / "docs" / "api" / "coinos-openapi.json"

sys.path.insert(0, str(_BACKEND_ROOT))

os.environ.setdefault("SKIP_STARTUP_HOOKS", "1")
os.environ.setdefault("SECRET_KEY", "openapi-export-dev-only-not-for-production")
os.environ.setdefault("OPENAPI_ENABLED", "false")
os.environ.setdefault("CACHE_ENABLED", "false")


_COINOS_PREFIX = "/api/coinos"


def export_coinos_spec(output: Path) -> None:
    """Export only CoinOS endpoints to a standalone OpenAPI JSON file."""
    from app import create_app
    from app.openapi import get_openapi_api

    app = create_app()
    api = get_openapi_api(app)
    if api is None:
        raise SystemExit("OpenAPI Api extension not registered")

    with app.app_context():
        full_spec = api.spec.to_dict()

    # Enrich with operationId, summary, tags, x-visibility
    from app.openapi.register import enrich_spec
    full_spec = enrich_spec(full_spec)

    # --- Filter to CoinOS paths only ---
    all_paths = full_spec.get("paths", {})
    coinos_paths = {
        path: item
        for path, item in all_paths.items()
        if path.startswith(_COINOS_PREFIX)
    }

    # --- Collect referenced schemas ---
    referenced_schemas = set()
    _collect_refs(coinos_paths, referenced_schemas)

    all_schemas = full_spec.get("components", {}).get("schemas", {})
    coinos_schemas = {
        name: schema
        for name, schema in all_schemas.items()
        if name in referenced_schemas
    }

    # --- Collect relevant tags ---
    all_tags = full_spec.get("tags", [])
    coinos_tag_names = set()
    for item in coinos_paths.values():
        for method_data in item.values():
            if isinstance(method_data, dict):
                for t in method_data.get("tags", []):
                    coinos_tag_names.add(t)

    coinos_tags = [t for t in all_tags if t.get("name") in coinos_tag_names]

    # --- Build standalone spec ---
    spec = {
        "openapi": full_spec.get("openapi", "3.0.3"),
        "info": {
            "title": "QuantDinger CoinOS Skills API",
            "version": "1.0.0",
            "description": (
                "CoinOS Skills integration — crypto market data (AiCoin 200+ exchanges), "
                "CEX trading (Binance/OKX/Bybit/etc.), Hyperliquid whale analytics, "
                "Freqtrade strategy management, on-chain DEX (OKX Web3), "
                "and exchange account management.\n\n"
                "Powered by [coinos-skills](https://github.com/aicoincom/coinos-skills)."
            ),
            "contact": {
                "name": "QuantDinger",
                "url": "https://github.com/brokermr810/quantdinger",
            },
            "license": {"name": "See repository LICENSE"},
        },
        "servers": [
            {"url": "http://localhost:5000", "description": "Backend direct"},
            {"url": "http://localhost:8888", "description": "Docker Compose"},
        ],
        "tags": coinos_tags,
        "paths": coinos_paths,
        "components": {
            "schemas": coinos_schemas,
            "securitySchemes": full_spec.get("components", {}).get("securitySchemes", {}),
        },
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote CoinOS OpenAPI spec ({len(coinos_paths)} paths) to {output}")


def _collect_refs(obj, refs: set) -> None:
    """Recursively collect all $ref schema names from an object."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "$ref" and isinstance(value, str):
                # Extract schema name from #/components/schemas/XXX
                if "/schemas/" in value:
                    refs.add(value.rsplit("/", 1)[-1])
            else:
                _collect_refs(value, refs)
    elif isinstance(obj, list):
        for item in obj:
            _collect_refs(item, refs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export CoinOS Skills OpenAPI spec")
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help=f"Output file (default: {_DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()
    export_coinos_spec(args.output)


if __name__ == "__main__":
    main()
