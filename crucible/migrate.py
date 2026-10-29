"""`crucible migrate`: bring runs recorded before Crucible 3.0.0 into the 3.0.0 layout and record.

    crucible migrate --dry-run                 say what would change; change nothing
    crucible migrate                           migrate runs/
    crucible migrate --runs runs-archive       any folder of runs, at any depth
    crucible migrate --bundle ironwood.json --to <site>/_data/crucible
                                               convert a published format-2 bundle into format-3 records

In order, for every run:
  1. Mint a legacy run_uuid into every meta.json that lacks one, before anything moves: a UUIDv5 of
     the machine (from the hostname the run recorded) and the run's pre-3.0.0 run_id, so the same
     run gets the same UUID every time, on any machine, and from its published bundle.
  2. Rewrite meta.json as the 3.0.0 run record (the old one is kept under local.legacy_meta), with
     the task's slug, publisher and format where the model key implies them, and no hardware for
     cloud runs.
  3. Turn check_results.json (with grader_results.json) into a score record at the rubric version it
     was scored under. The score is copied, never recomputed. The old files stay where they are.
  4. Move the folder from <model>/<category>/<test_id>/<timestamp> to <model>/<task>/<timestamp>.

Running it twice changes nothing.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from crucible import runrecord, workspace

LEGACY_CHECKS = "check_results.json"
LEGACY_GRADER = "grader_results.json"


def _meta_paths(runs_dir: Path) -> list[Path]:
    """Every run's meta.json under runs_dir, at any depth (runs-archive nests folders of runs)."""
    return sorted(p for p in runs_dir.rglob("meta.json")
                  if not {"workspace", "node_modules"}.intersection(p.relative_to(runs_dir).parts))


def _hostname(meta: dict, fallback: str) -> str:
    return ((meta.get("environment") or {}).get("machine") or {}).get("hostname") or fallback


def from_legacy(meta: dict, run_path: str, task_id: str) -> dict:
    """The 3.0.0 run record for a run recorded by Crucible 2.x."""
    env = meta.get("environment") or {}
    inference = env.get("inference") or {}
    variant = meta.get("model_variant") or {}
    test = meta.get("test") or {}
    model = meta.get("model")
    legacy_provenance = meta.get("provenance") or {}
    hostname = (env.get("machine") or {}).get("hostname")
    return {
        "record": "run", "format_version": runrecord.FORMAT_VERSION,
        "run_uuid": meta["run_uuid"],
        "run_path": run_path,
        "legacy_run_id": meta.get("run_id"),
        "started_at": meta.get("started_at"),
        "ended_at": meta.get("ended_at"),
        "elapsed_s": meta.get("elapsed_time"),
        "task": {"id": task_id, "version": test.get("version"), "rubric_version": test.get("rubric_version"),
                 "content_hash": test.get("content_hash"), "rubric_hash": test.get("rubric_hash"),
                 "alias": meta.get("test_id")},
        "harness": {"id": meta.get("agent"), "version": env.get("harness_version")},
        "model": runrecord.model_record(model, meta.get("reasoning") or "default", variant.get("reasoning_resolved"),
                                        inference, variant),
        "endpoint": runrecord.endpoint_record(model, inference, meta.get("endpoint")),
        "hardware": runrecord.hardware_record(model, env.get("machine"), inference),
        "outcome": {"status": meta.get("outcome"), "harness_status": meta.get("status"),
                    "returncode": meta.get("returncode"), "timed_out": meta.get("timed_out"),
                    "invalid": meta.get("invalid"), "leaks": list(meta.get("leaks") or [])},
        "metrics": meta.get("metrics") or {},
        "output_ref": None,
        "provenance": {**runrecord.null_provenance(), **legacy_provenance,
                       "machine_id": legacy_provenance.get("machine_id") or (
                           runrecord.legacy_machine_id(hostname) if hostname else None),
                       "machine_label": hostname, "source": "crucible-migrate"},
        "local": {
            "environment": env,
            "tools": meta.get("tools"),
            "watch": meta.get("watch"),
            "platform": meta.get("platform"),
            "checks": meta.get("checks"),
            "legacy_meta": meta,
        },
    }


def legacy_scores(run_dir: Path, run_uuid: str, task_id: str | None) -> list[dict]:
    """Score records from a 2.x check_results.json (and the grader_results.json it was scored with)."""
    checks = runrecord.read_json(run_dir / LEGACY_CHECKS)
    if not checks or checks.get("rubric_version") is None:
        return []
    grader = runrecord.read_json(run_dir / LEGACY_GRADER)
    rubric = None
    if task_id in workspace.all_task_ids():
        rubric = workspace.load_task(task_id).get("rubric")
    return [runrecord.score_from_checks(checks, run_uuid, grader, None, rubric)]


# Files a folder can hold and still count as empty
JUNK = {".DS_Store"}


def _remove_if_empty(folder: Path) -> None:
    if not folder.is_dir() or any(p.name not in JUNK for p in folder.iterdir()):
        return
    for p in folder.iterdir():
        p.unlink()
    folder.rmdir()


class Migration:
    def __init__(self, runs_dir: Path, dry_run: bool = False, machine: str | None = None):
        from crucible.bundle import machine_name
        self.runs_dir, self.dry_run = runs_dir, dry_run
        self.machine = machine or machine_name()
        self.counts = {"uuids": 0, "records": 0, "scores": 0, "moved": 0, "unchanged": 0}
        self.problems: list[str] = []
        self.aliases = workspace.aliases()
        self.minted: dict[Path, str] = {}  # what step 1 minted, so a dry run can carry on without writing

    def _save(self, path: Path, data: dict) -> None:
        if not self.dry_run:
            runrecord.write_json(path, data)

    def mint_uuids(self, meta_paths: list[Path]) -> None:
        """Step 1: every run gets its run_uuid before anything is renamed or moved."""
        for path in meta_paths:
            meta = runrecord.read_json(path)
            if not isinstance(meta, dict) or meta.get("run_uuid"):
                continue
            if not meta.get("run_id"):
                self.problems.append(f"{path.parent}: no run_id to derive a run_uuid from; left as is")
                continue
            meta["run_uuid"] = runrecord.legacy_run_uuid(_hostname(meta, self.machine), meta["run_id"])
            self.minted[path] = meta["run_uuid"]
            self._save(path, meta)
            self.counts["uuids"] += 1

    def convert(self, path: Path) -> None:
        """Steps 2 to 4 for one run."""
        run_dir = path.parent
        meta = runrecord.read_json(path)
        if not isinstance(meta, dict):
            self.problems.append(f"{run_dir}: meta.json isn't readable; left as is")
            return
        if runrecord.is_record(meta):
            self._ensure_scores(run_dir, meta)
            return
        meta.setdefault("run_uuid", self.minted.get(path))
        if not meta.get("run_uuid"):
            return  # reported in step 1
        rel = run_dir.relative_to(self.runs_dir).parts
        if len(rel) < 4:
            self.problems.append(f"{run_dir}: not in the <model>/<category>/<test>/<timestamp> layout; left as is")
            return
        old_id = meta.get("test_id") or rel[-2]
        task_id = self.aliases.get(old_id.lower()) or (old_id if old_id in workspace.all_task_ids() else None)
        if task_id is None:
            self.problems.append(f"{run_dir}: unknown test ID {old_id} (not in docs/task-id-map.json); left as is")
            return
        model_dir = run_dir.parent.parent.parent
        target = model_dir / task_id / run_dir.name
        if target.exists():
            self.problems.append(f"{run_dir}: {target} already exists; left as is")
            return
        run_path = f"{model_dir.name}/{task_id}/{run_dir.name}"
        record = from_legacy(meta, run_path, task_id)
        scores = legacy_scores(run_dir, meta["run_uuid"], task_id)
        self.counts["records"] += 1
        self.counts["scores"] += len(scores)
        self.counts["moved"] += 1
        if self.dry_run:
            return
        for score in scores:
            runrecord.write_score(run_dir, score)
        runrecord.write_json(path, record)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(run_dir), str(target))
        for parent in (run_dir.parent, run_dir.parent.parent):  # the old <test_id> and <category> folders
            _remove_if_empty(parent)

    def _ensure_scores(self, run_dir: Path, meta: dict) -> None:
        """A run already migrated: add a score record only if one is missing (a migration interrupted midway)."""
        added = 0
        for score in legacy_scores(run_dir, meta["run_uuid"], meta["task"]["id"]):
            if not runrecord.score_path(run_dir, score["rubric_version"], score["method"]).exists():
                added += 1
                if not self.dry_run:
                    runrecord.write_score(run_dir, score)
        self.counts["scores"] += added
        self.counts["unchanged"] += not added

    def run(self) -> dict:
        paths = _meta_paths(self.runs_dir)
        self.mint_uuids(paths)
        for path in paths:
            self.convert(path)
        # Folders a run left without a meta.json (stopped before it was recorded) aren't runs: report them
        for prompt in sorted(self.runs_dir.rglob("prompt.txt")):
            if not (prompt.parent / "meta.json").exists() and "workspace" not in prompt.relative_to(self.runs_dir).parts:
                self.problems.append(f"{prompt.parent.relative_to(self.runs_dir)}: no meta.json (an unfinished run); left as is")
        return self.counts


# --------------------------------------------------------------------------
# Format-2 bundles
# --------------------------------------------------------------------------

def _bundle_hardware(run: dict) -> dict | None:
    hw = run.get("hardware")
    if not hw or runrecord.where(run.get("model"), run.get("inference")) != "local":
        return None
    return runrecord.hardware_record(run.get("model"), hw, {"same_machine": True})


def bundle_records(bundle: dict) -> list[tuple[dict, str | None, list[dict]]]:
    """(run record, output, score records) for every run in a format-2 bundle."""
    machine = (bundle.get("source") or {}).get("machine") or "unknown"
    tests = {t["id"]: t for t in bundle.get("tests") or []}
    aliases = workspace.aliases()
    out = []
    for run in bundle.get("runs") or []:
        legacy_id = run.get("run_id")
        test_id = run.get("test_id") or ""
        task_id = aliases.get(test_id.lower()) or test_id
        run_uuid = run.get("run_uuid") or runrecord.legacy_run_uuid(machine, legacy_id)
        model_dir, _, rest = (legacy_id or "").partition("/")
        test = tests.get(test_id) or {}
        inference = run.get("inference") or {}
        record = {
            "record": "run", "format_version": runrecord.FORMAT_VERSION,
            "run_uuid": run_uuid, "run_path": f"{model_dir}/{task_id}/{rest.rsplit('/', 1)[-1]}" if legacy_id else None,
            "legacy_run_id": legacy_id,
            "started_at": run.get("started_at"), "ended_at": None, "elapsed_s": run.get("elapsed_s"),
            "task": {"id": task_id, "version": run.get("test_version"),
                     "rubric_version": test.get("rubric_version") if run.get("check_score") is not None else None,
                     "content_hash": None, "rubric_hash": None, "alias": test_id},
            "harness": {"id": run.get("harness"), "version": run.get("harness_version")},
            "model": runrecord.model_record(run.get("model"), run.get("reasoning") or "default",
                                            (run.get("model_variant") or {}).get("reasoning_resolved"), inference,
                                            run.get("model_variant")),
            "endpoint": runrecord.endpoint_record(run.get("model"), inference, run.get("endpoint")),
            "hardware": _bundle_hardware(run),
            "outcome": {"status": run.get("outcome"), "harness_status": run.get("status"), "returncode": None,
                        "timed_out": run.get("timed_out"), "invalid": None, "leaks": []},
            "metrics": {k: run.get(k) for k in ("tests_passed", "tests_failed", "tool_calls", "tokens_in", "tokens_out",
                                                "model_responses", "ttft_s", "response_time_avg_s", "cost_usd",
                                                "reasoning_chars")},
            "output_ref": None,
            "provenance": {**runrecord.null_provenance(), **{k: v for k, v in (run.get("provenance") or {}).items() if v},
                           "machine_id": (run.get("provenance") or {}).get("machine_id") or runrecord.legacy_machine_id(machine),
                           "machine_label": machine, "source": "bundle-format-2"},
        }
        scores = []
        if run.get("check_score") is not None and test.get("rubric_version") is not None:
            legacy = {"scorer": {"type": "tests" if run.get("hidden_tests") else "checks"},
                      "rubric_version": test["rubric_version"], "criteria": run.get("criteria"),
                      "scores": {"_overall": run["check_score"]}, "checks": run.get("checks"),
                      "capped_at": None, "passed": None}
            grader = {"tests": (run.get("hidden_tests") or {}).get("tests") or []}
            scores.append(runrecord.score_from_checks(legacy, run_uuid, grader))
        out.append((record, run.get("output"), scores))
    return out


def convert_bundle(path: Path, to: Path, outputs: Path, dry_run: bool = False):
    """Add a format-2 bundle's runs to a format-3 folder; runs already there (same run_uuid) are skipped."""
    from crucible import bundle as publisher
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format_version") != 2:
        raise SystemExit(f"{path} is format {data.get('format_version')}, not 2")
    pub = publisher.Publisher(to, outputs, dry_run)
    for record, output, scores in bundle_records(data):
        pub.add(publisher.published_run(record, output), output, scores, [])
    return pub


def main() -> None:
    parser = argparse.ArgumentParser(prog="crucible migrate", description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, default=Path("runs"), help="A folder of runs, at any depth (default: runs)")
    parser.add_argument("--dry-run", action="store_true", help="Say what would change; change nothing")
    parser.add_argument("--machine", help="Hostname for runs that didn't record one (default: this machine's)")
    parser.add_argument("--bundle", type=Path, help="Convert this format-2 bundle into format-3 records instead")
    parser.add_argument("--to", type=Path, help="With --bundle: the format-3 folder (_data/crucible) to add to")
    parser.add_argument("--outputs", type=Path, help="With --bundle: where outputs go (default: beside _data)")
    args = parser.parse_args()

    if args.bundle:
        from crucible.bundle import default_outputs
        if not args.to:
            parser.error("--bundle needs --to <site>/_data/crucible")
        pub = convert_bundle(args.bundle, args.to, args.outputs or default_outputs(args.to), args.dry_run)
        c = pub.counts
        print(f"{'Would add' if args.dry_run else 'Added'} {c['runs']} runs and {c['scores']} score records from "
              f"{args.bundle}")
        if pub.errors:
            print("Not written (invalid):\n  " + "\n  ".join(pub.errors[:30]))
            sys.exit(1)
        return

    if not args.runs.is_dir():
        sys.exit(f"No runs folder at {args.runs}")
    migration = Migration(args.runs, args.dry_run, args.machine)
    c = migration.run()
    verb = "Would" if args.dry_run else "Did"
    print(f"{verb}: mint {c['uuids']} run UUIDs, rewrite {c['records']} run records, write {c['scores']} score "
          f"records, move {c['moved']} folders; {c['unchanged']} runs already migrated")
    for problem in migration.problems:
        print(f"  {problem}")
    if args.dry_run:
        print("Dry run: nothing was changed.")


if __name__ == "__main__":
    main()
