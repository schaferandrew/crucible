"""A small JSON Schema checker for the site-data schemas (crucible/schemas/site-data/*.json).

Supports type (a name or a list), enum, const, oneOf, minimum, minItems, maxItems, required, properties,
additionalProperties (as a schema), items, prefixItems, and
`$ref` to `#/$defs/<name>`: the subset those schemas use. Returns the problems found, empty when valid.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas" / "site-data"
NAMES = ("meta", "index", "cell-runs", "recent-index", "task", "model", "run", "recent")
TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool,
         "null": type(None)}


def load(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def _type_ok(data, names) -> bool:
    for name in [names] if isinstance(names, str) else names:
        if name in ("integer", "number") and isinstance(data, bool):
            continue
        if isinstance(data, TYPES[name]):
            return True
    return False


def problems(data, schema: dict, root: dict | None = None, path: str = "$") -> list:
    root = root or schema
    if "$ref" in schema:
        schema = root["$defs"][schema["$ref"].rsplit("/", 1)[-1]]
    if "type" in schema and not _type_ok(data, schema["type"]):
        return [f"{path}: expected {schema['type']}, got {type(data).__name__}"]
    found = []
    if "enum" in schema and data not in schema["enum"]:
        found.append(f"{path}: {data!r} isn't one of {schema['enum']}")
    if "const" in schema and (data != schema["const"] or isinstance(data, bool) != isinstance(schema["const"], bool)):
        found.append(f"{path}: {data!r} isn't {schema['const']!r}")
    if "oneOf" in schema and sum(not problems(data, sub, root, path) for sub in schema["oneOf"]) != 1:
        found.append(f"{path}: doesn't match exactly one of the allowed shapes")
    if "minimum" in schema and isinstance(data, (int, float)) and not isinstance(data, bool) and data < schema["minimum"]:
        found.append(f"{path}: {data!r} is below {schema['minimum']}")
    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            found.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            found.append(f"{path}: more than {schema['maxItems']} items")
        for i, sub in enumerate(schema.get("prefixItems") or []):
            if i < len(data):
                found += problems(data[i], sub, root, f"{path}[{i}]")
    if isinstance(data, dict):
        found += [f"{path}: missing '{k}'" for k in schema.get("required", []) if k not in data]
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in data:
                found += problems(data[key], sub, root, f"{path}.{key}")
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            for key, value in data.items():
                if key not in props:
                    found += problems(value, extra, root, f"{path}[{key!r}]")
    if isinstance(data, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(data):
            found += problems(item, schema["items"], root, f"{path}[{i}]")
    return found


def check(name: str, data) -> list:
    return problems(data, load(name))
