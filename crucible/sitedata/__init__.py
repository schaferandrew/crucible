"""`crucible site-data`: the bundle as the static JSON the dashboard loads (docs/site-data-format.md)."""
from __future__ import annotations

import argparse
import sys

from crucible.sitedata.build import build

__all__ = ["build", "main"]


def main() -> None:
    p = argparse.ArgumentParser(prog="crucible site-data", description="Turn a published bundle into the dashboard's static JSON")
    p.add_argument("--bundle", required=True, help="the bundle folder (catalog/, runs/, scores/, status/)")
    p.add_argument("--outputs", help="the folder of model outputs (<run_uuid>.txt), copied to <out>/outputs/")
    p.add_argument("--out", required=True, help="where to write the site data")
    p.add_argument("--display", help="display settings YAML (hidden_suites)")
    p.add_argument("--fallbacks", help="display text YAML merged into catalogs that lack it")
    p.add_argument("--built-at", help="build time to record (default: SOURCE_DATE_EPOCH, else the bundle's latest record)")
    args = p.parse_args()
    result = build(args.bundle, args.outputs, args.out, display=args.display, fallbacks=args.fallbacks, built_at=args.built_at)
    total = sum(result["sizes"].values())
    print(f"site data: {len(result['sizes'])} files, {total / 1e6:.1f} MB, written to {args.out}")
    for sid, c in result["counts"].items():
        print(f"  {sid}: " + ", ".join(f"{k} {v}" for k, v in c.items() if v))
    if result["skipped"]:
        print(f"  {result['skipped']} records skipped (newer format or unreadable)", file=sys.stderr)
