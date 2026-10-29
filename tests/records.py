"""Run records for tests: a minimal 3.0.0 meta.json, written into a run folder."""
import json
from pathlib import Path

from crucible import runrecord


def run_meta(task_id: str, version=None, rubric_version=None, model: str = "lmstudio/m", harness: str = "direct",
             run_path: str | None = None, run_uuid: str = "00000000-0000-4000-8000-000000000001",
             inference: dict | None = None, **outcome) -> dict:
    inference = inference if inference is not None else {"provider": "lmstudio", "local": True, "same_machine": True}
    machine = {"hostname": "Ironwood", "cpu": "Apple M1 Pro", "gpu": None, "ram_gb": 32.0}
    return {
        "record": "run", "format_version": 3, "run_uuid": run_uuid,
        "run_path": run_path or f"{model.replace('/', '_')}/{task_id}/20260101_000000", "legacy_run_id": None,
        "started_at": "2026-01-01T00:00:00+00:00", "ended_at": "2026-01-01T00:00:01+00:00", "elapsed_s": 1.0,
        "task": {"id": task_id, "version": version, "rubric_version": rubric_version, "content_hash": None,
                 "rubric_hash": None, "alias": None},
        "harness": {"id": harness, "version": None},
        "model": runrecord.model_record(model, "default", None, inference),
        "endpoint": runrecord.endpoint_record(model, inference),
        "hardware": runrecord.hardware_record(model, machine, inference),
        "outcome": {"status": "completed", "harness_status": "COMPLETE", "returncode": 0, "timed_out": False,
                    "invalid": None, "leaks": [], **outcome},
        "metrics": {"tokens_out": 12},
        "output_ref": None,
        "provenance": runrecord.null_provenance(),
        "local": {"environment": {"machine": machine, "inference": inference}},
    }


def write_run(run_dir: Path, meta: dict, output: str = "") -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (run_dir / "stdout.txt").write_text(output, encoding="utf-8")
    return run_dir
