#!/usr/bin/env python3
"""Results bundles: the JSON files the portfolio's Crucible page reads.

`crucible publish` writes this machine's runs as one bundle into the page's data folder
(_data/crucible/<machine>.json) and checks it against crucible/schemas/results.schema.json.
Bundles from other machines go in the same folder; the page merges them.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
from pathlib import Path

from crucible import exporter

SCHEMA_PATH = Path(__file__).parent / "schemas" / "results.schema.json"
# Where publish writes when --to isn't given: the portfolio checkout next to this one
DEFAULT_DIRS = [Path(os.environ["CRUCIBLE_PUBLISH_DIR"])] if os.environ.get("CRUCIBLE_PUBLISH_DIR") else []
DEFAULT_DIRS.append(Path(__file__).resolve().parents[2] / "schaferandrew.github.io" / "_data" / "crucible")

TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float),
         "boolean": bool, "null": type(None)}


def problems(data, schema: dict | None = None, path: str = "$") -> list[str]:
    """Where data breaks the schema (the subset it uses: type, enum, required, properties, items)."""
    schema = schema if schema is not None else json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    found = []
    types = schema.get("type")
    if types:
        allowed = tuple(t for name in ([types] if isinstance(types, str) else types) for t in
                        (TYPES[name] if isinstance(TYPES[name], tuple) else (TYPES[name],)))
        # bool is an int in Python; don't let True pass as a number
        if not isinstance(data, allowed) or (isinstance(data, bool) and bool not in allowed):
            return [f"{path}: expected {types}, got {type(data).__name__}"]
    if "enum" in schema and data not in schema["enum"]:
        found.append(f"{path}: {data!r} isn't one of {schema['enum']}")
    if isinstance(data, dict):
        found += [f"{path}: missing '{key}'" for key in schema.get("required", []) if key not in data]
        for key, sub in schema.get("properties", {}).items():
            if key in data:
                found += problems(data[key], sub, f"{path}.{key}")
    if isinstance(data, list) and "items" in schema:
        for i, item in enumerate(data):
            found += problems(item, schema["items"], f"{path}[{i}]")
    return found


def machine_name() -> str:
    return re.sub(r"[^a-z0-9-]+", "-", platform.node().split(".")[0].lower()).strip("-") or "machine"


def main() -> None:
    parser = argparse.ArgumentParser(prog="crucible publish",
                                     description="Write this machine's results as a bundle the Crucible page picks up.")
    parser.add_argument("--to", type=Path, help="The page's data folder (default: CRUCIBLE_PUBLISH_DIR, else "
                                                "../schaferandrew.github.io/_data/crucible)")
    parser.add_argument("--name", default=machine_name(), help="Bundle file name (default: this machine's name)")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--check", type=Path, metavar="FILE", help="Only validate an existing bundle")
    args = parser.parse_args()

    if args.check:
        found = problems(json.loads(args.check.read_text(encoding="utf-8")))
        print("\n".join(found[:30]) if found else f"{args.check} is a valid results bundle.")
        sys.exit(1 if found else 0)

    folder = args.to or next((d for d in DEFAULT_DIRS if d.parent.exists()), None)
    if folder is None:
        sys.exit("No data folder found; pass --to <portfolio>/_data/crucible (or set CRUCIBLE_PUBLISH_DIR).")
    data = exporter.export(args.runs)
    data["source"] = {"machine": args.name}
    found = problems(data)
    if found:
        sys.exit("The bundle doesn't match the schema:\n" + "\n".join(found[:30]))
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{args.name}.json"
    # Plain UTF-8, not \u escapes: Jekyll parses data files with a YAML parser that rejects escaped emoji
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    counted = sum(r["counts"] for r in data["runs"])
    print(f"Wrote {len(data['runs'])} runs ({counted} count toward scores) to {out}")
