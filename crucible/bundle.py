#!/usr/bin/env python3
"""`crucible publish`: write results into the dashboard's data folder as bundle format 3.

Format 3 (docs/bundle-format.md) is one file per thing, so publishing only ever adds files:

  <to>/catalog/<suite>.json                          what each suite is: tasks, tiers, weights
  <to>/runs/<yyyy-mm>/<run_uuid>.json                one run record, never edited
  <to>/scores/<yyyy-mm>/<run_uuid>.r<n>.<method>.json one score record per rubric version and method
  <to>/status/<run_uuid>.json                        status records (invalidations), append-only
  <outputs>/<run_uuid>.txt                           the model's full output, outside _data

Publishing twice writes nothing; nothing published is deleted or rewritten, except the latest
suite's catalog (task names and summaries may change) and status files (only appended to). Every
file is validated before it's written, and `crucible publish --check <to>` validates a folder and
recomputes every run's content hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
from pathlib import Path

from crucible import checks, exporter, provenance, runrecord, suites, workspace

SCHEMAS = Path(__file__).parent / "schemas"
SCHEMA_PATH = SCHEMAS / "results.schema.json"   # format 2 (`crucible export --format 2`)
RECORD_SCHEMAS = {kind: SCHEMAS / f"{kind}.schema.json" for kind in ("catalog", "run", "score", "status")}
# Counts additive, optional fields across the bundle (docs/versioning.md#bundle-format). 1: model.origin on runs
FORMAT_REVISION = 1
# Where publish writes when --to isn't given: the portfolio checkout next to this one
DEFAULT_DIRS = [Path(os.environ["CRUCIBLE_PUBLISH_DIR"])] if os.environ.get("CRUCIBLE_PUBLISH_DIR") else []
DEFAULT_DIRS.append(Path(__file__).resolve().parents[2] / "schaferandrew.github.io" / "_data" / "crucible")
CHANGELOG_URL = "https://github.com/schaferandrew/crucible/blob/main/SUITE_CHANGELOG.md"

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


def record_problems(kind: str, data) -> list[str]:
    return problems(data, json.loads(RECORD_SCHEMAS[kind].read_text(encoding="utf-8")))


def machine_name() -> str:
    return re.sub(r"[^a-z0-9-]+", "-", platform.node().split(".")[0].lower()).strip("-") or "machine"


# --------------------------------------------------------------------------
# Records as published
# --------------------------------------------------------------------------

def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def content_hash(record: dict, output: str | None) -> str:
    """SHA-256 over the run record without its provenance, plus the output text: an edited copy shows."""
    digest = hashlib.sha256(canonical({k: v for k, v in record.items() if k != "provenance"}))
    digest.update(b"\0" + (output or "").encode("utf-8"))
    return "sha256:" + digest.hexdigest()


def month(record: dict) -> str:
    return (record.get("started_at") or "unknown")[:7] or "unknown"


def derived_metrics(run_dir: Path, meta: dict) -> dict:
    """Metrics 3.5.0 records at run time, worked out from a run's stored artifacts for an older run.

    meta.json is never edited, so a run made before the metric existed gets it here, in the record being
    published. Nothing is added when the harness's timing files are gone or report no token counts.
    """
    from crucible.agents import AGENTS
    from crucible.metrics import timing_summary
    metrics = meta.get("metrics") or {}
    agent = AGENTS.get((meta.get("harness") or {}).get("id"))
    if agent is None or "output_tokens_per_s" in metrics:
        return {}
    speed = timing_summary(agent.response_timings(run_dir))["output_tokens_per_s"]
    return {"output_tokens_per_s": speed} if speed is not None else {}


def published_run(meta: dict, output: str | None) -> dict:
    """The run record as it's published: no local fields, an output reference and its content hash."""
    record = runrecord.published(meta)
    record["output_ref"] = f"outputs/{record['run_uuid']}.txt" if output else None
    record["provenance"] = {**runrecord.null_provenance(), **(record.get("provenance") or {})}
    record["provenance"]["content_hash"] = content_hash(record, output)
    return record


def published_score(score: dict) -> dict:
    # The scored text is the published output; it isn't repeated in every score record
    return {k: v for k, v in score.items() if k != "checked_text"}


def score_name(score: dict) -> str:
    return f"{score['run_uuid']}.r{score['rubric_version']}.{score['method']}.json"


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------

def _scoring(p: dict) -> dict:
    from crucible import graders
    rubric = p.get("rubric") or []
    if p.get("grader"):
        expected = graders.expected_tests(p["grader"]) if checks.per_test(p) else None
        if checks.per_test(p):
            return {"method": "hidden_tests", "unit": "tests", "total": len(expected) if expected else None,
                    "scale": runrecord.SCALE}
        return {"method": "hidden_tests", "unit": "points", "total": sum(i["max_score"] for i in rubric),
                "scale": runrecord.SCALE}
    if checks.fully_checked(p):
        return {"method": "checks", "unit": "points", "total": sum(i["max_score"] for i in rubric), "scale": runrecord.SCALE}
    return {"method": "judge", "unit": "points", "total": sum(i.get("max_score", 0) for i in rubric), "scale": runrecord.SCALE}


def catalog(suite_name: str, suites_dir: Path | None = None) -> dict:
    """What a suite is, for the dashboard: every label, threshold and weight it needs, so it hard-codes none."""
    from crucible.agents import AGENTS
    from crucible.taxonomy import (AREAS, CATEGORY_WEIGHTS, MODE_BLURBS, MODE_HARNESSES, MODE_LABELS, MODES,
                                   TIER_INFO, mode_for)
    suite = suites.load(suite_name, suites_dir)
    all_names = suites.names(suites_dir)
    pinned = suites.pins(suite)
    first_pinned = {}
    for name in all_names:
        for task_id in suites.pins(suites.load(name, suites_dir)):
            first_pinned.setdefault(task_id, name)
    weights = suite.get("category_weights") or CATEGORY_WEIGHTS
    tiers = {t["id"]: t for t in suite.get("tiers") or []}
    tasks = []
    for task_id in workspace.all_task_ids():
        p = workspace.load_task(task_id)
        pin = pinned.get(task_id)
        tasks.append({
            "id": task_id, "name": p.get("name"), "aliases": list(p.get("aliases") or []),
            "mode": mode_for(p), "area": p.get("area"),
            "category": (pin or p).get("category"), "tier": (pin or p).get("tier"),
            "status": "active" if pin else ("retired" if p.get("status") == "retired" else "provisional"),
            "version": (pin or p).get("version"), "rubric_version": (pin or p).get("rubric_version"),
            "weight": pin.get("weight") if pin else None,
            "scoring": _scoring(p),
            "criteria": [{"id": i["criterion"], "label": i["criterion"], "max_score": i.get("max_score")}
                         for i in p.get("rubric") or []],
            "summary": exporter._first_sentence(p.get("prompt", "")),
            "prompt": (p.get("prompt") or "").strip(),
            "rules": [c.get("rule", c["type"]) for c in p.get("checks") or []],
            "added_in": first_pinned.get(task_id),
        })
    newest = all_names[-1] == suite_name
    return {
        "format_version": runrecord.FORMAT_VERSION, "format_revision": FORMAT_REVISION,
        "suite": {"id": suite_name, "version": suite.get("version"), "cut_at": suite.get("cut_at"),
                  "status": "current" if newest else "past",
                  "changelog_url": f"{CHANGELOG_URL}#suite-{suite_name.replace('.', '')}"},
        "crucible_version": provenance.crucible_version(),
        "scoring_policy": suite.get("scoring_policy") or {},
        "modes": [{"id": m, "label": MODE_LABELS[m], "blurb": MODE_BLURBS[m], "order": i + 1} for i, m in enumerate(MODES)],
        "areas": [{"id": a, "label": label, "mode": m, "order": i + 1}
                  for m in MODES for i, (a, label) in enumerate(AREAS[m].items())],
        "categories": [{"id": c, "label": c.replace("_", " ").capitalize(), "weight": w} for c, w in weights.items()],
        "tiers": [{"id": t, "label": TIER_INFO.get(t, {}).get("label", t), "blurb": TIER_INFO.get(t, {}).get("blurb"),
                   "order": i + 1, "role": info.get("role"), **({"gate": info["gate"]} if info.get("gate") else {})}
                  for i, (t, info) in enumerate(tiers.items())],
        "harnesses": [{"id": h, "label": h, "modes": [m for m in MODES if h in MODE_HARNESSES[m]]} for h in AGENTS],
        "tasks": tasks,
    }


# --------------------------------------------------------------------------
# Publishing
# --------------------------------------------------------------------------

class Publisher:
    """Adds records to a format-3 folder, never rewriting one already there."""

    def __init__(self, to: Path, outputs: Path, dry_run: bool = False):
        self.to, self.outputs, self.dry_run = to, outputs, dry_run
        self.counts = {"runs": 0, "scores": 0, "status": 0, "catalogs": 0, "outputs": 0, "invalid": 0}
        self.errors: list[str] = []
        self.skipped: list[str] = []
        self.runs = {p.stem for p in (to / "runs").glob("*/*.json")}
        self.scores = {p.name for p in (to / "scores").glob("*/*.json")}

    def _write(self, kind: str, path: Path, data) -> bool:
        found = record_problems(kind, data)
        if found:
            self.errors.append(f"{path.relative_to(self.to)}: " + "; ".join(found[:5]))
            self.counts["invalid"] += 1
            return False
        if not self.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Plain UTF-8, not \u escapes: Jekyll parses data files with a YAML parser that rejects escaped emoji
            path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return True

    def add(self, record: dict, output: str | None, score_records: list[dict], status: list[dict]) -> None:
        uuid, folder = record["run_uuid"], month(record)
        if uuid not in self.runs:
            if output and not self.dry_run:
                self.outputs.mkdir(parents=True, exist_ok=True)
                (self.outputs / f"{uuid}.txt").write_text(output, encoding="utf-8")
                self.counts["outputs"] += 1
            if self._write("run", self.to / "runs" / folder / f"{uuid}.json", record):
                self.runs.add(uuid)
                self.counts["runs"] += 1
        for score in score_records:
            name = score_name(score)
            if name not in self.scores and self._write("score", self.to / "scores" / folder / name, published_score(score)):
                self.scores.add(name)
                self.counts["scores"] += 1
        if status:
            path = self.to / "status" / f"{uuid}.json"
            have = runrecord.read_json(path) or []
            # Append-only: only entries past what's published are added
            if len(status) > len(have) and status[:len(have)] == have and self._write("status", path, status):
                self.counts["status"] += len(status) - len(have)

    def add_catalogs(self, suites_dir: Path | None = None) -> None:
        names = suites.names(suites_dir)
        for name in names:
            path = self.to / "catalog" / f"{name}.json"
            data = catalog(name, suites_dir)
            old = runrecord.read_json(path)
            # A past suite's catalog never changes; the current one follows task names and summaries
            if old is None or (name == names[-1] and old != data):
                if self._write("catalog", path, data):
                    self.counts["catalogs"] += 1


def harness_problem(meta: dict) -> str | None:
    """Why a run's harness can't count for its task's mode (chat: direct; agentic: opencode, pi), if it can't."""
    from crucible.taxonomy import harness_problem as problem
    try:
        task = workspace.load_task(meta["task"]["id"])
    except FileNotFoundError:
        return None
    return problem(task, (meta.get("harness") or {}).get("id"))


def publish(runs_dir: Path, to: Path, outputs: Path, dry_run: bool = False) -> Publisher:
    runrecord.require_migrated(runs_dir)
    pub = Publisher(to, outputs, dry_run)
    for run_dir in runrecord.run_dirs(runs_dir):
        meta = runrecord.read(run_dir)
        if not meta.get("run_uuid"):
            pub.errors.append(f"{run_dir}: no run_uuid (run `crucible migrate`)")
            continue
        problem = harness_problem(meta)
        if problem:
            # Not comparable, so never published (matching `crucible export`); the run stays in runs/
            pub.skipped.append(f"{meta.get('run_path') or run_dir.name}: {problem}")
            continue
        output = checks.final_answer(run_dir) or None
        meta = {**meta, "metrics": {**(meta.get("metrics") or {}), **derived_metrics(run_dir, meta)}}
        pub.add(published_run(meta, output), output, runrecord.scores(run_dir), runrecord.statuses(run_dir))
    pub.add_catalogs()
    return pub


def check_folder(to: Path, outputs: Path | None = None) -> list[str]:
    """Every problem in a format-3 folder: schema, file names, and run content hashes."""
    found = []
    for kind, pattern in (("catalog", "catalog/*.json"), ("run", "runs/*/*.json"), ("score", "scores/*/*.json"),
                          ("status", "status/*.json")):
        for path in sorted(to.glob(pattern)):
            rel = path.relative_to(to)
            data = runrecord.read_json(path)
            if data is None:
                found.append(f"{rel}: not valid JSON")
                continue
            found += [f"{rel}: {p}" for p in record_problems(kind, data)]
            if kind == "run":
                if data.get("run_uuid") != path.stem:
                    found.append(f"{rel}: file name isn't its run_uuid")
                ref = data.get("output_ref")
                output = None
                if ref and outputs is not None:
                    out_path = outputs / Path(ref).name
                    if not out_path.exists():
                        found.append(f"{rel}: output {ref} is missing")
                        continue
                    output = out_path.read_text(encoding="utf-8")
                if outputs is not None or not ref:
                    if (data.get("provenance") or {}).get("content_hash") != content_hash(data, output):
                        found.append(f"{rel}: content hash doesn't match (the record or its output was edited)")
            elif kind == "score" and path.name != score_name(data):
                found.append(f"{rel}: file name doesn't match its run_uuid, rubric version and method")
    return found


def default_outputs(to: Path) -> Path:
    """Outputs live outside _data, so Jekyll never parses them: <site>/crucible-data/outputs."""
    return to.parent.parent / "crucible-data" / "outputs" if to.parent.name == "_data" else to / "outputs"


def main() -> None:
    parser = argparse.ArgumentParser(prog="crucible publish", description=__doc__.splitlines()[0])
    parser.add_argument("--to", type=Path, help="The page's data folder (default: CRUCIBLE_PUBLISH_DIR, else "
                                                "../schaferandrew.github.io/_data/crucible)")
    parser.add_argument("--outputs", type=Path, help="Where full outputs go (default: <site>/crucible-data/outputs)")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--dry-run", action="store_true", help="Say what would be added; write nothing")
    parser.add_argument("--check", type=Path, metavar="DIR", help="Only validate a published folder and its content hashes")
    args = parser.parse_args()

    if args.check:
        found = check_folder(args.check, args.outputs or default_outputs(args.check))
        print("\n".join(found[:50]) if found else f"{args.check} is a valid format-3 folder.")
        sys.exit(1 if found else 0)

    folder = args.to or next((d for d in DEFAULT_DIRS if d.parent.exists()), None)
    if folder is None:
        sys.exit("No data folder found; pass --to <portfolio>/_data/crucible (or set CRUCIBLE_PUBLISH_DIR).")
    pub = publish(args.runs, folder, args.outputs or default_outputs(folder), args.dry_run)
    c = pub.counts
    verb = "Would add" if args.dry_run else "Added"
    print(f"{verb} {c['runs']} runs, {c['scores']} score records, {c['status']} status records, "
          f"{c['catalogs']} catalogs to {folder}; {c['outputs']} outputs")
    if pub.skipped:
        print(f"Skipped {len(pub.skipped)} runs through a harness their mode doesn't use (kept in {args.runs}/):\n  "
              + "\n  ".join(pub.skipped[:30]))
    if pub.errors:
        print("Not written (invalid):\n  " + "\n  ".join(pub.errors[:30]))
        sys.exit(1)


if __name__ == "__main__":
    main()
