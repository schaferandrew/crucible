#!/usr/bin/env python3
"""`crucible publish`: write results into the dashboard's data folder as bundle format 3.

Format 3 (docs/bundle-format.md) is one file per thing, so publishing only ever adds files:

  <to>/catalog/<suite>.json                          what each suite is: tasks, tiers, weights
  <to>/runs/<yyyy-mm>/<run_uuid>.json                one run record, never edited
  <to>/scores/<yyyy-mm>/<run_uuid>.r<n>.<method>.json one score record per rubric version and method
  <to>/status/<run_uuid>.json                        status records (invalidations), append-only
  <to>/registry/<name>.json                          the registry (registry/*.yaml): makers, models, packagers, machines
  <to>/corrections.json                              the registry's aliases in the shape the legacy page reads
  <to>/manifest.json                                 generated index of every run (crucible/manifest.py rules)
  <outputs>/<run_uuid>.txt                           the model's full output, outside _data

Publishing twice writes nothing; a run already published with a different hash is rejected; nothing published is deleted or rewritten, except the latest
suite's catalog (task names and summaries may change), status files (only appended to), the
registry files and corrections.json (reviewed data about how to read recorded model fields). Every
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

from crucible import checks, exporter, manifest, provenance, registry, runrecord, suites, workspace

SCHEMAS = Path(__file__).parent / "schemas"
SCHEMA_PATH = SCHEMAS / "results.schema.json"   # format 2 (`crucible export --format 2`)
REGISTRY_KINDS = tuple(f"registry-{name}" for name in registry.NAMES)
RECORD_SCHEMAS = {kind: SCHEMAS / f"{kind}.schema.json"
                  for kind in ("catalog", "run", "run.v4", "score", "status", "corrections") + REGISTRY_KINDS}
# The legacy page reads this, generated from the registry (registry/models.yaml and packagers.yaml)
CORRECTIONS_FILE = "corrections.json"
# Counts additive, optional fields across the bundle (docs/versioning.md#bundle-format). 1: model.origin on runs;
# 2: corrections.json and model.reasoning.resolved_source; 3: registry/*.json
FORMAT_REVISION = 3
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


def record_problems(kind: str, data, strict: bool = False) -> list[str]:
    """Where a record breaks its schema. Run records switch schema on format_version (3 or 4).

    A `local` key never leaves the machine: it's an error in a format-4 record always, and in a record
    of either format when `strict` (what publish writes). `--check` isn't strict about format 3, because
    19 runs were published with one before publish dropped it; those stay as published and are warned about.
    """
    version = data.get("format_version") if isinstance(data, dict) else None
    schema = "run.v4" if kind == "run" and version == 4 else kind
    found = problems(data, json.loads(RECORD_SCHEMAS[schema].read_text(encoding="utf-8")))
    if kind == "run" and isinstance(data, dict):
        if "local" in data and (strict or version == 4):
            found.append("$.local: a `local` key never leaves the machine and can't be published")
        if version == 4:
            for dotted in runrecord.V4_DROPPED:
                node = data
                for part in dotted.split("."):
                    node = node.get(part, _MISSING) if isinstance(node, dict) else _MISSING
                if node is not _MISSING:
                    found.append(f"$.{dotted}: not part of format 4")
    return found


_MISSING = object()


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
    null = runrecord.null_provenance_v4() if record.get("format_version") == 4 else runrecord.null_provenance()
    record["provenance"] = {**null, **(record.get("provenance") or {})}
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

def _text(data) -> str:
    # Plain UTF-8, not \u escapes: Jekyll parses data files with a YAML parser that rejects escaped emoji
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def scan(to: Path, only: set[str] | None = None) -> dict[str, dict]:
    """Manifest entries read from the files in a folder: run_uuid -> entry (hash as the run file states it)."""
    scores: dict[str, list[str]] = {}
    for p in (to / "scores").glob("*/*.json"):
        uuid, _, rest = p.name.partition(".")
        scores.setdefault(uuid, []).append(rest[:-len(".json")])
    status = {p.stem: len(runrecord.read_json(p) or []) for p in (to / "status").glob("*.json")}
    found = {}
    for path in sorted(to.glob("runs/*/*.json")):
        if only is not None and path.stem not in only:
            continue
        run = runrecord.read_json(path)
        if isinstance(run, dict):
            found[path.stem] = manifest.entry((run.get("provenance") or {}).get("content_hash"),
                                              path.relative_to(to).as_posix(), manifest.submitter_of(run),
                                              scores.get(path.stem), status.get(path.stem, 0))
    return found


def write_manifest(to: Path, known: dict[str, dict] | None = None) -> bool:
    """Regenerate <to>/manifest.json from the files, keeping the submitter of every entry in `known`
    (and entries whose run file is gone, so `--check` still reports them). True when the file changed."""
    known = known or {}
    runs = dict(known)
    for uuid, found in scan(to).items():
        runs[uuid] = {**found, "submitter": (known.get(uuid) or {}).get("submitter") or found["submitter"]}
    text = manifest.dump({**manifest.empty(), "runs": dict(sorted(runs.items()))})
    path = to / manifest.FILE
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def known_entries(to: Path) -> dict[str, dict]:
    """What's published: the manifest's entries, plus any run file in the folder it doesn't list yet
    (a folder published before manifests existed)."""
    listed = runrecord.read_json(to / manifest.FILE)
    entries = dict(listed["runs"]) if isinstance(listed, dict) and isinstance(listed.get("runs"), dict) else {}
    on_disk = {p.stem for p in (to / "runs").glob("*/*.json")}
    entries.update(scan(to, on_disk - set(entries)))
    return entries


class Publisher:
    """Adds records to a bundle folder, never rewriting one already there (rules: crucible/manifest.py)."""

    def __init__(self, to: Path, outputs: Path, dry_run: bool = False, submitter: str | None = None,
                 skip_known: bool = False):
        # skip_known: a run whose uuid is already published is left alone even when this copy hashes
        # differently, instead of rejected (`crucible migrate --bundle` converting an old bundle)
        self.to, self.outputs, self.dry_run, self.submitter, self.skip_known = to, outputs, dry_run, submitter, skip_known
        self.counts = {"runs": 0, "scores": 0, "status": 0, "catalogs": 0, "corrections": 0, "registry": 0, "outputs": 0, "invalid": 0}
        self.errors: list[str] = []
        self.skipped: list[str] = []
        self.rejected: list[str] = []
        self.entries = known_entries(to)
        self.scores = {p.name for p in (to / "scores").glob("*/*.json")}

    def _write(self, kind: str, path: Path, data) -> bool:
        found = record_problems(kind, data, strict=True)
        if found:
            self.errors.append(f"{path.relative_to(self.to)}: " + "; ".join(found[:5]))
            self.counts["invalid"] += 1
            return False
        if not self.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_text(data), encoding="utf-8")
        return True

    def add(self, record: dict, output: str | None, score_records: list[dict], status: list[dict]) -> None:
        uuid, folder = record["run_uuid"], month(record)
        path = self.to / "runs" / folder / f"{uuid}.json"
        rel = path.relative_to(self.to).as_posix()
        existing = self.entries.get(uuid)
        new_hash = (record.get("provenance") or {}).get("content_hash")
        same_bytes = None
        if existing is not None and existing.get("content_hash") is None and new_hash is None:
            file = self.to / existing["path"]
            same_bytes = file.exists() and file.read_text(encoding="utf-8") == _text(record)
        verdict, why = manifest.decide(existing, new_hash, same_bytes)
        if verdict == manifest.REJECT and self.skip_known:
            return
        if verdict == manifest.REJECT:
            message = f"{rel}: rejected, run {uuid} is {why}; a published run is never overwritten"
            self.rejected.append(message)
            self.errors.append(message)
            return
        if verdict == manifest.ADD:
            if output and not self.dry_run:
                self.outputs.mkdir(parents=True, exist_ok=True)
                (self.outputs / f"{uuid}.txt").write_text(output, encoding="utf-8")
                self.counts["outputs"] += 1
            if self._write("run", path, record):
                self.entries[uuid] = manifest.entry(new_hash, rel, self.submitter or manifest.submitter_of(record))
                self.counts["runs"] += 1
            else:
                return
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

    def write_manifest(self) -> bool:
        """Regenerate manifest.json from what's now on disk (nothing in a dry run)."""
        return False if self.dry_run else write_manifest(self.to, self.entries)

    def add_catalogs(self, suites_dir: Path | None = None) -> None:
        names = suites.names(suites_dir)
        for name in names:
            path = self.to / "catalog" / f"{name}.json"
            data = catalog(name, suites_dir)
            old = runrecord.read_json(path)
            # A past suite's catalog never changes, except its status when a newer suite is cut; the latest one follows task names and summaries
            if old is None or (name == names[-1] and old != data) or (old != data and old["suite"]["status"] != data["suite"]["status"]):
                if self._write("catalog", path, data):
                    self.counts["catalogs"] += 1

    def add_corrections(self, reg: registry.Registry | None = None) -> None:
        """Rewritten whole, like the registry: it's reviewed data generated from it, never a run."""
        path, data = self.to / CORRECTIONS_FILE, corrections(reg)
        if runrecord.read_json(path) != data and self._write("corrections", path, data):
            self.counts["corrections"] += 1

    def add_registry(self, reg: registry.Registry | None = None) -> None:
        """The registry (registry/*.yaml) as registry/<name>.json, rewritten whole when it changed."""
        reg = reg or registry.load()
        for name, data in reg.files().items():
            path = self.to / "registry" / f"{name}.json"
            if runrecord.read_json(path) != data and self._write(f"registry-{name}", path, data):
                self.counts["registry"] += 1


def corrections(reg: registry.Registry | None = None) -> dict:
    """The legacy corrections record, generated from the registry: every model alias is a correction
    (to its id, or its `legacy_to_base` spelling), every packager spelling a publisher fix
    (docs/bundle-format.md#corrections)."""
    reg = reg or registry.load()
    models, publishers = [], []
    for model in reg.models.values():
        for alias in model.get("aliases") or []:
            entry = {"base": alias["base"], "to_base": alias.get("legacy_to_base") or model["id"], "maker": model["maker"]}
            if alias.get("packager"):
                entry["publisher"] = alias["packager"]
            models.append({**entry, "reason": alias["reason"].strip()})
    for packager in reg.packagers.values():
        publishers += [{"from": s, "to": packager["id"]} for s in packager.get("spellings") or []]
    return {"record": "corrections", "format_version": runrecord.FORMAT_VERSION, "models": models, "publishers": publishers}


def harness_problem(meta: dict) -> str | None:
    """Why a run's harness can't count for its task's mode (chat: direct; agentic: opencode, pi), if it can't."""
    from crucible.taxonomy import harness_problem as problem
    try:
        task = workspace.load_task(meta["task"]["id"])
    except FileNotFoundError:
        return None
    return problem(task, (meta.get("harness") or {}).get("id"))


def publish(runs_dir: Path, to: Path, outputs: Path, dry_run: bool = False, submitter: str | None = None) -> Publisher:
    runrecord.require_migrated(runs_dir)
    pub = Publisher(to, outputs, dry_run, submitter)
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
    reg = registry.load()
    found = reg.problems()
    if found:
        pub.errors += [f"registry: {p}" for p in found]
    else:
        pub.add_registry(reg)
        pub.add_corrections(reg)
    pub.write_manifest()
    return pub


def copy_bundle(old: Path, new: Path, from_outputs: Path, outputs: Path, dry_run: bool = False,
                submitter: str | None = None) -> dict:
    """Copy a published bundle into another folder without changing a byte of any record.

    Every run's content hash is verified against its record and output first; a run that fails isn't
    copied. Runs follow the manifest rules (crucible/manifest.py), so copying twice is a no-op. Scores,
    status files, catalogs, the registry and corrections.json are copied byte for byte too; one that
    already exists in `new` with different bytes is an error, never overwritten. Ends by writing
    <new>/manifest.json. Returns counts, `errors` and `notes`.
    """
    report = {"runs": 0, "scores": 0, "status": 0, "catalogs": 0, "registry": 0, "corrections": 0, "outputs": 0,
              "verified": 0, "unverifiable": 0, "unchanged": 0, "errors": [], "notes": []}
    errors, rejected = report["errors"], set()
    known = known_entries(new)

    def put(src: Path, dest: Path, kind: str) -> bool:
        data = src.read_bytes()
        if dest.exists():
            if dest.read_bytes() == data:
                report["unchanged"] += 1
            else:
                errors.append(f"{dest.relative_to(new).as_posix()}: already in {new} with different bytes; not overwritten")
            return False
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        if kind:
            report[kind] += 1
        return True

    for path in sorted(old.glob("runs/*/*.json")):
        rel, uuid = path.relative_to(old), path.stem
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
        ref, output, source = data.get("output_ref"), None, None
        if ref:
            source = from_outputs / Path(ref).name
            if not source.exists():
                errors.append(f"{rel.as_posix()}: output {ref} is missing from {from_outputs}")
                rejected.add(uuid)
                continue
            output = source.read_text(encoding="utf-8")
        stored = (data.get("provenance") or {}).get("content_hash")
        if unverifiable(data):
            report["unverifiable"] += 1
        elif stored != content_hash(data, output):
            errors.append(f"{rel.as_posix()}: content hash doesn't match (the record or its output was edited); not copied")
            rejected.add(uuid)
            continue
        else:
            report["verified"] += 1
        dest = new / rel
        verdict, why = manifest.decide(known.get(uuid), stored, dest.exists() and dest.read_bytes() == raw)
        if verdict == manifest.REJECT:
            errors.append(f"{rel.as_posix()}: rejected, run {uuid} is {why}")
            rejected.add(uuid)
            continue
        put(path, dest, "runs" if verdict == manifest.ADD else "")
        if source is not None:
            put(source, outputs / source.name, "outputs")
        known.setdefault(uuid, manifest.entry(stored, rel.as_posix(), submitter or manifest.submitter_of(data)))
    for pattern, kind in (("scores/*/*.json", "scores"), ("status/*.json", "status"), ("catalog/*.json", "catalogs"),
                          ("registry/*.json", "registry")):
        for path in sorted(old.glob(pattern)):
            if path.name.partition(".")[0] in rejected or path.stem in rejected:
                continue
            put(path, new / path.relative_to(old), kind)
    if (old / CORRECTIONS_FILE).exists():
        put(old / CORRECTIONS_FILE, new / CORRECTIONS_FILE, "corrections")
    handled = {"runs", "scores", "status", "catalog", "registry", CORRECTIONS_FILE, manifest.FILE}
    left = sorted(p.name for p in old.iterdir() if p.name not in handled and not p.name.startswith("."))
    if left:
        report["notes"].append("not copied: " + ", ".join(left))
    if not dry_run and not errors:
        write_manifest(new, known)
    elif not dry_run:
        report["notes"].append("manifest.json not written: fix the errors and copy again")
    return report


def manifest_problems(to: Path) -> list[str]:
    path = to / manifest.FILE
    return manifest.problems(runrecord.read_json(path), scan(to)) if path.exists() else []


def check_folder(to: Path, outputs: Path | None = None) -> list[str]:
    """Every problem in a format-3 folder: schema, file names, and run content hashes."""
    found = []
    corrections = to / CORRECTIONS_FILE
    if corrections.exists():
        found += [f"{CORRECTIONS_FILE}: {p}" for p in record_problems("corrections", runrecord.read_json(corrections))]
    for name in registry.NAMES:
        path = to / "registry" / f"{name}.json"
        if path.exists():
            found += [f"registry/{name}.json: {p}" for p in record_problems(f"registry-{name}", runrecord.read_json(path))]
    reg = check_registry(to)
    if reg is not None:
        found += [f"registry: {p}" for p in reg.problems()]
    for kind, pattern in (("catalog", "catalog/*.json"), ("run", "runs/*/*.json"), ("score", "scores/*/*.json"),
                          ("status", "status/*.json")):
        for path in sorted(to.glob(pattern)):
            rel = path.relative_to(to)
            data = runrecord.read_json(path)
            if data is None:
                found.append(f"{rel}: not valid JSON")
                continue
            problems_here = record_problems(kind, data)
            if kind == "run" and unverifiable(data):
                # Published before every record was hashed, without an output: nothing to check it against
                problems_here = [p for p in problems_here if not p.startswith("$.provenance.content_hash:")]
            found += [f"{rel}: {p}" for p in problems_here]
            if kind == "run" and unverifiable(data):
                if data.get("run_uuid") != path.stem:
                    found.append(f"{rel}: file name isn't its run_uuid")
            elif kind == "run":
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
    return found + manifest_problems(to)


def unverifiable(run: dict) -> bool:
    """A run published with no content hash and no output: written before publish hashed every record
    (a format-2 bundle converted by an older `crucible migrate`, or an early 3.x publish). There's
    nothing to check it against. Runs are never edited, so these stay; `--check` lists every one as a
    warning instead of failing, so a stripped hash is still visible. A record with a hash that doesn't
    match, or with an output and no hash, is still an error."""
    prov = run.get("provenance") or {}
    return not run.get("output_ref") and not prov.get("content_hash")


def unverifiable_warnings(to: Path) -> list[str]:
    found = sorted(str(p.relative_to(to)) for p in to.glob("runs/*/*.json") if unverifiable(runrecord.read_json(p) or {}))
    return [f"{len(found)} runs have no output and no content hash (published before records were hashed), "
            "so they can't be verified: "
            + ", ".join(Path(f).stem[:8] for f in found)] if found else []


def check_registry(to: Path) -> registry.Registry | None:
    """The registry a folder is checked against: the repo's (what the next publish sends), else the
    folder's own registry/ copy, else None."""
    if registry.REGISTRY_DIR.joinpath("makers.yaml").exists():
        return registry.load()
    try:
        return registry.load(to)
    except (FileNotFoundError, OSError):
        return None


def published_runs(to: Path):
    for path in sorted(to.glob("runs/*/*.json")):
        run = runrecord.read_json(path)
        if isinstance(run, dict):
            yield run


def base_warnings(to: Path, reg: registry.Registry | None = None) -> list[str]:
    """Published bases the registry doesn't resolve to a model: one line per base, with how many runs
    carry it. Warnings, never errors: published runs can't be edited."""
    reg = reg or check_registry(to)
    if reg is None:
        return []
    seen: dict[str, int] = {}
    for run in published_runs(to):
        base = (run.get("model") or {}).get("base")
        if base and reg.model_for_base(base) is None:
            seen[base] = seen.get(base, 0) + 1
    return [f"model.base {b!r} ({n} runs) isn't a registry model" + (f" ({', '.join(unnormalized(b))})" if unnormalized(b) else "")
            + "; add the model, or an alias with a reason, to registry/models.yaml" for b, n in sorted(seen.items())]


def machine_warnings(to: Path, reg: registry.Registry | None = None) -> list[str]:
    """Local runs that don't resolve to a machine or a hardware key, with the host names they carry."""
    reg = reg or check_registry(to)
    if reg is None:
        return []
    no_machine: dict[str, int] = {}
    no_key: dict[str, int] = {}
    for run in published_runs(to):
        res = reg.resolve_run(run)
        if res.where != "local":
            continue
        hosts = ", ".join(sorted({h for h in ((run.get("endpoint") or {}).get("device"), (run.get("hardware") or {}).get("label")) if h})) or "no host recorded"
        if res.machine is None:
            no_machine[hosts] = no_machine.get(hosts, 0) + 1
        if res.hardware_key is None:
            no_key[hosts] = no_key.get(hosts, 0) + 1
    found = []
    if no_machine:
        found.append(f"{sum(no_machine.values())} local runs resolve to no machine: "
                     + "; ".join(f"{h} ({n})" for h, n in sorted(no_machine.items())) + "; add the host name to registry/machines.yaml")
    if no_key:
        found.append(f"{sum(no_key.values())} local runs resolve to no hardware key: "
                     + "; ".join(f"{h} ({n})" for h, n in sorted(no_key.items())))
    return found


def legacy_warnings(to: Path) -> list[str]:
    """Runs already published with a leaked `local` key or a null content hash. Never edited, only listed."""
    local = hashless = 0
    for run in published_runs(to):
        local += "local" in run
        hashless += not (run.get("provenance") or {}).get("content_hash")
    found = []
    if local:
        found.append(f"{local} runs carry a `local` key (published before publish dropped it); they stay as published")
    if hashless:
        found.append(f"{hashless} runs have a null content_hash; they stay as published")
    return found


def unnormalized(base: str) -> list[str]:
    """Why a recorded base doesn't look like <maker>/<model>, if it doesn't."""
    cleaned, fmt, quant, publisher = runrecord.clean_base_model(base)
    issues = []
    if publisher:
        issues.append(f"packager prefix '{publisher}'")
    if fmt or quant:
        issues.append("format or quant tag in the name")
    if base.startswith("~"):
        issues.append("OpenRouter '~' alias prefix")
    if base.endswith(":free") or base.endswith("-free"):
        issues.append("provider tier suffix")
    if "/" not in (cleaned or "") and not publisher:
        issues.append("no maker")
    return issues


def default_outputs(to: Path) -> Path:
    """Outputs live outside _data, so Jekyll never parses them: <site>/crucible-data/outputs."""
    return to.parent.parent / "crucible-data" / "outputs" if to.parent.name == "_data" else to / "outputs"


def main() -> None:
    parser = argparse.ArgumentParser(prog="crucible publish", description=__doc__.splitlines()[0])
    parser.add_argument("--to", type=Path, help="The bundle folder (default: CRUCIBLE_PUBLISH_DIR, else "
                                                "../schaferandrew.github.io/_data/crucible)")
    parser.add_argument("--outputs", type=Path, help="Where full outputs go (default: <site>/crucible-data/outputs, or <to>/outputs)")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--dry-run", action="store_true", help="Say what would be added; write nothing")
    parser.add_argument("--check", type=Path, metavar="DIR", help="Only validate a published folder, its content hashes and its manifest")
    parser.add_argument("--from-bundle", type=Path, metavar="OLD", help="Copy the published bundle OLD into --to byte for byte "
                                                                      "(verifying every content hash) instead of publishing runs/")
    parser.add_argument("--from-outputs", type=Path, help="With --from-bundle: where OLD's outputs are (default: next to OLD, like --outputs)")
    parser.add_argument("--submitter", help="Recorded in the manifest for the runs this call adds")
    args = parser.parse_args()

    if args.check:
        found = check_folder(args.check, args.outputs or default_outputs(args.check))
        print("\n".join(found[:50]) if found else f"{args.check} is a valid bundle folder.")
        reg = check_registry(args.check)
        warnings = (unverifiable_warnings(args.check) + base_warnings(args.check, reg) + machine_warnings(args.check, reg)
                    + legacy_warnings(args.check))
        if not (args.check / manifest.FILE).exists():
            warnings.append(f"no {manifest.FILE}; `crucible publish` writes it")
        if warnings:
            print("Warnings (not errors):\n  " + "\n  ".join(warnings))
        sys.exit(1 if found else 0)

    folder = args.to or next((d for d in DEFAULT_DIRS if d.parent.exists()), None)
    if folder is None:
        sys.exit("No data folder found; pass --to <portfolio>/_data/crucible (or set CRUCIBLE_PUBLISH_DIR).")
    if args.from_bundle:
        if args.to is None:
            sys.exit("--from-bundle needs --to: the folder to copy into.")
        report = copy_bundle(args.from_bundle, folder, args.from_outputs or default_outputs(args.from_bundle),
                             args.outputs or default_outputs(folder), args.dry_run, args.submitter)
        verb = "Would copy" if args.dry_run else "Copied"
        print(f"{verb} {report['runs']} runs ({report['verified']} hashes verified, {report['unverifiable']} unverifiable), "
              f"{report['scores']} scores, {report['status']} status files, {report['catalogs']} catalogs, "
              f"{report['registry']} registry files, {report['corrections']} corrections files, {report['outputs']} outputs "
              f"to {folder}; {report['unchanged']} files were already there")
        for note in report["notes"]:
            print(note)
        if report["errors"]:
            print("Problems:\n  " + "\n  ".join(report["errors"][:30]))
            sys.exit(1)
        return
    pub = publish(args.runs, folder, args.outputs or default_outputs(folder), args.dry_run, args.submitter)
    c = pub.counts
    verb = "Would add" if args.dry_run else "Added"
    print(f"{verb} {c['runs']} runs, {c['scores']} score records, {c['status']} status records, "
          f"{c['catalogs']} catalogs, {c['registry']} registry files, {c['corrections']} corrections files "
          f"to {folder}; {c['outputs']} outputs")
    if pub.skipped:
        print(f"Skipped {len(pub.skipped)} runs through a harness their mode doesn't use (kept in {args.runs}/):\n  "
              + "\n  ".join(pub.skipped[:30]))
    if pub.errors:
        print("Not written (invalid or rejected):\n  " + "\n  ".join(pub.errors[:30]))
        sys.exit(1)


if __name__ == "__main__":
    main()
