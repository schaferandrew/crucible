"""crucible export --format 2: a score counts only on the current task and rubric versions."""
import json

import pytest

from crucible import exporter, runrecord, workspace
from tests.records import run_meta, write_run

TASK = "fire-truck-color"  # formerly KNOW-1


def _run(tmp_path, task_version, rubric_version, agent_overall=8.0, inference=None, model="lmstudio/m"):
    meta = run_meta(TASK, task_version, rubric_version, model=model, inference=inference)
    meta["local"]["environment"]["machine"]["cpu"] = "Apple M1 Pro"
    write_run(tmp_path / meta["run_path"], meta, "Red.")
    (tmp_path / meta["run_path"] / "agent_results.json").write_text(json.dumps({
        "scores": {"_overall": agent_overall}, "rubric_version": rubric_version, "summary": "fine",
        "scorer": {"type": "agent", "model": "claude-opus-5-5", "prompt_version": 1}}))
    return tmp_path


def test_current_run_counts(tmp_path):
    p = workspace.load_task(TASK)
    data = exporter.export(_run(tmp_path, p["version"], p["rubric_version"], inference={
        "provider": "lmstudio", "local": True, "same_machine": True, "endpoint_host": "10.0.0.5",
        "quantization": "Q4_0", "context_length": 8192}))
    (run,) = data["runs"]
    assert run["counts"] and run["agent_score"] == 8.0 and run["tokens_out"] == 12
    assert run["hardware"]["hostname"] == "Ironwood"
    assert run["inference"]["quantization"] == "Q4_0"
    # The endpoint's address never leaves the machine
    assert "endpoint_host" not in run["inference"]
    # Format 2 keeps the pre-3.0.0 IDs, so the live dashboard keeps working
    assert run["test_id"] == "KNOW-1" and run["run_id"] == f"lmstudio_m/{TASK}/20260101_000000"
    test = next(t for t in data["tests"] if t["id"] == "KNOW-1")
    assert test["slug"] == TASK and test["tier"] and test["version"] == p["version"]


def test_lm_link_run_reports_the_serving_machine(tmp_path):
    p = workspace.load_task(TASK)
    served = {"provider": "lmstudio", "local": True, "same_machine": False, "served_via": "LM Link",
              "device": "Whitehall", "quantization": "Q4_K_M"}
    (run,) = exporter.export(_run(tmp_path, p["version"], p["rubric_version"], inference=served))["runs"]
    assert run["hardware"]["hostname"] == "Whitehall"
    assert run["inference"]["device"] == "Whitehall"


def test_older_task_version_does_not_count(tmp_path):
    p = workspace.load_task(TASK)
    (run,) = exporter.export(_run(tmp_path, p["version"] - 1 or None, p["rubric_version"]))["runs"]
    assert not run["counts"] and run["agent_score"] is None


def test_stale_rubric_score_dropped(tmp_path):
    p = workspace.load_task(TASK)
    (run,) = exporter.export(_run(tmp_path, p["version"], p["rubric_version"] + 1))["runs"]
    assert run["counts"] and run["agent_score"] is None


def test_check_score_comes_from_the_score_record_at_the_current_rubric(tmp_path):
    p = workspace.load_task(TASK)
    runs = _run(tmp_path, p["version"], p["rubric_version"])
    (run_dir,) = runrecord.run_dirs(runs)
    legacy = {"scorer": {"type": "checks"}, "rubric_version": p["rubric_version"], "scores": {"_overall": 7.5},
              "criteria": [{"criterion": "Red", "max_score": 4, "score": 3, "detail": "said red"}], "checks": []}
    runrecord.write_score(run_dir, runrecord.score_from_checks(legacy, "u"))
    (run,) = exporter.export(runs)["runs"]
    assert run["check_score"] == 7.5
    assert run["criteria"] == [{"criterion": "Red", "max_score": 4, "score": 3, "detail": "said red"}]
    runrecord.write_score(run_dir, runrecord.score_from_checks({**legacy, "rubric_version": 0}, "u"))
    (run_dir / "scores" / f"r{p['rubric_version']}.checks.json").unlink()
    (run,) = exporter.export(runs)["runs"]
    assert run["check_score"] is None and run["criteria"] is None


def test_invalid_run_is_left_out(tmp_path):
    p = workspace.load_task(TASK)
    runs = _run(tmp_path, p["version"], p["rubric_version"])
    (run_dir,) = runrecord.run_dirs(runs)
    runrecord.add_status(run_dir, "u", invalid={"reason": "stale server on the fixture port"})
    assert exporter.export(runs)["runs"] == []


def test_tests_carry_the_full_prompt():
    t = next(t for t in exporter.export_tests() if t["id"] == "HIST-2")
    assert t["prompt"] == workspace.load_task("HIST-2")["prompt"].strip()
    assert t["prompt"].startswith(t["summary"])


def test_cloud_run_exports_no_hardware(tmp_path):
    """The laptop that sent the request didn't run the model."""
    p = workspace.load_task(TASK)
    cloud = {"provider": "openrouter", "local": False, "same_machine": None, "endpoint_host": "openrouter.ai"}
    (run,) = exporter.export(_run(tmp_path, p["version"], p["rubric_version"], inference=cloud,
                                  model="openrouter/a/b"))["runs"]
    assert run["hardware"] is None and run["hardware_key"] is None


def test_migrated_runs_export_their_2_x_identity_fields(tmp_path):
    from crucible import bundle
    p = workspace.load_task(TASK)
    runs = _run(tmp_path, p["version"], p["rubric_version"])
    (run_dir,) = runrecord.run_dirs(runs)
    meta = json.loads((run_dir / "meta.json").read_text())
    meta["legacy_run_id"] = "lmstudio_m/everyday/KNOW-1/20260101_000000"
    meta["local"]["legacy_meta"] = {"test_id": "KNOW-1"}  # recorded before 2.4.0: no identity fields
    (run_dir / "meta.json").write_text(json.dumps(meta))
    data = exporter.export(runs)
    (run,) = data["runs"]
    assert run["run_id"] == "lmstudio_m/everyday/KNOW-1/20260101_000000"
    for key in ("provenance", "model_variant", "hardware_key", "endpoint"):
        assert run[key] is None
    assert run["run_uuid"] == meta["run_uuid"]
    assert data["format_version"] == 2
    assert bundle.problems(data) == []


def test_new_runs_export_identity_and_variant(tmp_path):
    from crucible import bundle
    p = workspace.load_task(TASK)
    inference = {"provider": "lmstudio", "local": True, "same_machine": True, "publisher": "lmstudio-community",
                 "format": "gguf", "quantization": "Q4_0"}
    data = exporter.export(_run(tmp_path, p["version"], p["rubric_version"], inference=inference))
    (run,) = data["runs"]
    assert run["hardware_key"] == "m1-pro-32gb"
    assert run["model_variant"] == {"publisher": "lmstudio-community", "format": "gguf", "quant": "Q4_0",
                                    "reasoning_resolved": None}
    assert bundle.problems(data) == []
    run["provenance"]["crucible_dirty"] = "no"
    assert any("provenance.crucible_dirty" in p for p in bundle.problems(data))


def test_export_refuses_runs_from_before_3(tmp_path):
    legacy = tmp_path / "m" / "everyday" / "KNOW-1" / "20260101_000000"
    legacy.mkdir(parents=True)
    (legacy / "meta.json").write_text(json.dumps({"run_id": "m/everyday/KNOW-1/20260101_000000", "test_id": "KNOW-1"}))
    with pytest.raises(SystemExit, match="crucible migrate"):
        exporter.export(tmp_path)
