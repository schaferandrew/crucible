"""crucible export: a score counts only on the current test and rubric versions."""
import json

from crucible import exporter, workspace


def _run(tmp_path, test_version, rubric_version, agent_overall=8.0):
    run_dir = tmp_path / "m" / "everyday" / "KNOW-1" / "20260101_000000"
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(json.dumps({
        "run_id": "m/everyday/KNOW-1/20260101_000000", "test_id": "KNOW-1", "agent": "direct",
        "model": "lmstudio/m", "status": "COMPLETE", "timed_out": False, "elapsed_time": 1.0,
        "test": {"version": test_version},
        "environment": {"machine": {"hostname": "Ironwood", "cpu": "Apple MATH-1 Pro", "ram_gb": 32.0},
                        "inference": {"provider": "lmstudio", "local": True, "same_machine": True,
                                      "endpoint_host": "10.0.0.5", "quantization": "Q4_0", "context_length": 8192}},
        "metrics": {"tokens_out": 12},
    }))
    (run_dir / "agent_results.json").write_text(json.dumps({
        "scores": {"_overall": agent_overall}, "rubric_version": rubric_version, "summary": "fine",
        "scorer": {"type": "agent", "model": "claude-opus-5-5", "prompt_version": 1}}))
    return tmp_path


def test_current_run_counts(tmp_path):
    p = workspace.load_prompt("KNOW-1")
    data = exporter.export(_run(tmp_path, p["version"], p["rubric_version"]))
    (run,) = data["runs"]
    assert run["counts"] and run["agent_score"] == 8.0 and run["tokens_out"] == 12
    assert run["hardware"]["hostname"] == "Ironwood"
    assert run["inference"]["quantization"] == "Q4_0"
    # The endpoint's address never leaves the machine
    assert "endpoint_host" not in run["inference"]
    test = next(t for t in data["tests"] if t["id"] == "KNOW-1")
    assert test["tier"] and test["version"] == p["version"]


def test_older_test_version_does_not_count(tmp_path):
    p = workspace.load_prompt("KNOW-1")
    (run,) = exporter.export(_run(tmp_path, p["version"] - 1 or None, p["rubric_version"]))["runs"]
    assert not run["counts"] and run["agent_score"] is None


def test_stale_rubric_score_dropped(tmp_path):
    p = workspace.load_prompt("KNOW-1")
    (run,) = exporter.export(_run(tmp_path, p["version"], p["rubric_version"] + 1))["runs"]
    assert run["counts"] and run["agent_score"] is None


def test_invalid_run_is_left_out(tmp_path):
    p = workspace.load_prompt("KNOW-1")
    runs = _run(tmp_path, p["version"], p["rubric_version"])
    (meta_path,) = runs.glob("*/*/*/*/meta.json")
    meta = json.loads(meta_path.read_text())
    meta["invalid"] = {"reason": "stale server on the fixture port"}
    meta_path.write_text(json.dumps(meta))
    assert exporter.export(runs)["runs"] == []
