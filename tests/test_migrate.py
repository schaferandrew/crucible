"""crucible migrate: pre-3.0.0 runs into the new layout and record, without changing a score."""
import json
import shutil
import uuid

import pytest

from crucible import bundle, exporter, migrate, runrecord, workspace


def _legacy_run(root, model, category, test_id, ts, hostname="Ironwood", check_score=None, rubric_version=1,
                grader=None, inference=None, **extra):
    run_id = f"{model}/{category}/{test_id}/{ts}"
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    env = {"machine": {"hostname": hostname, "cpu": "Apple M1 Pro", "gpu": None, "ram_gb": 32.0} if hostname else {},
           "inference": inference if inference is not None else {"provider": "lmstudio", "local": True,
                                                                  "same_machine": True, "quantization": "4bit"},
           "harness_version": None}
    meta = {"run_id": run_id, "test_id": test_id, "agent": "direct", "model": model.replace("_", "/", 2),
            "reasoning": "default", "started_at": f"2026-10-{ts[6:8]}T00:00:00+00:00", "elapsed_time": 3.5,
            "returncode": 0, "timed_out": False, "status": "COMPLETE", "outcome": "completed",
            "test": {"version": 1, "rubric_version": rubric_version, "content_hash": "c", "rubric_hash": "r"},
            "environment": env, "metrics": {"tokens_out": 5}, **extra}
    (run_dir / "meta.json").write_text(json.dumps(meta))
    (run_dir / "stdout.txt").write_text("Canberra")
    (run_dir / "prompt.txt").write_text("What is the capital?")
    if check_score is not None:
        (run_dir / "check_results.json").write_text(json.dumps({
            "run_id": run_id, "test_id": test_id, "scorer": {"type": "tests" if grader else "checks"},
            "criteria": [{"criterion": "Capitals", "max_score": 6, "score": check_score * 0.6, "detail": "d"},
                         {"criterion": "No big-city traps", "max_score": 4, "score": check_score * 0.4, "detail": "e"}],
            "capped_at": None, "test_version": 1, "rubric_version": rubric_version, "rubric_hash": "r",
            "scores": {"_overall": check_score}, "checks": [{"id": "capitals", "type": "required_patterns",
                                                             "passed": True, "detail": "d", "rule": "names them"}],
            "passed": False, "checked_text": "Canberra", "scored_at": "2026-10-01T00:00:00+00:00"}))
    if grader:
        (run_dir / "grader_results.json").write_text(json.dumps(grader))
    return run_dir


@pytest.fixture
def tree(tmp_path):
    runs = tmp_path / "runs"
    _legacy_run(runs, "lmstudio_qwen_qwen3.5-9b", "geography", "GEOG-1", "20261020_010101", check_score=7.5)
    _legacy_run(runs, "lmstudio_qwen_qwen3.5-9b", "geography", "GEOG-1", "20261021_010101", check_score=10.0,
                rubric_version=2)
    # Recorded before hostnames were, under a 0.x ID (COD1 -> CODE-1 -> interest-cli-open-ended)
    _legacy_run(runs, "openrouter_openai_gpt-x", "coding_build", "COD1", "20260902_010101", hostname=None,
                inference={}, agent="opencode")
    tests = [{"file": "a", "group": "contract", "name": n, "passed": p, "error": None if p else "boom\nmore"}
             for n, p in [("one", True), ("two", True), ("three", False), ("four", True)]]
    _legacy_run(runs, "lmstudio_qwen_qwen3.5-9b", "coding_debug", "CODE-16", "20261022_010101", check_score=7.5,
                grader={"tests": tests})
    # runs-archive nests folders of runs one level deeper
    _legacy_run(tmp_path / "runs-archive" / "bad-runs", "lmstudio_qwen_qwen3.5-9b", "writing", "WRIT-3",
                "20261023_010101", invalid={"reason": "stale server"})
    (runs / "lmstudio_qwen_qwen3.5-9b" / "geography" / "GEOG-1" / ".DS_Store").write_text("")
    return tmp_path


def _tree(folder):
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def _migrate(folder, **kw):
    m = migrate.Migration(folder, machine="ironwood", **kw)
    m.run()
    return m


def test_dry_run_changes_nothing(tree):
    before = _tree(tree)
    m = _migrate(tree / "runs", dry_run=True)
    assert m.counts["uuids"] == 4 and m.counts["records"] == 4 and m.counts["scores"] == 3 and m.counts["moved"] == 4
    assert _tree(tree) == before


def test_migrating_twice_changes_nothing(tree):
    first = _migrate(tree / "runs")
    assert first.problems == []
    after = _tree(tree)
    second = _migrate(tree / "runs")
    assert second.counts == {"uuids": 0, "records": 0, "scores": 0, "moved": 0, "unchanged": 4}
    assert _tree(tree) == after


def test_runs_move_to_the_new_layout_with_the_same_scores(tree):
    runs = tree / "runs"
    before = {json.loads(p.read_text())["run_id"]: json.loads(p.read_text()).get("scores", {}).get("_overall")
              for p in runs.rglob("check_results.json")}
    _migrate(runs)
    assert runrecord.legacy_run_dirs(runs) == []
    dirs = runrecord.run_dirs(runs)
    assert [d.relative_to(runs).as_posix() for d in dirs] == [
        "lmstudio_qwen_qwen3.5-9b/capitals-not-largest-city/20261020_010101",
        "lmstudio_qwen_qwen3.5-9b/capitals-not-largest-city/20261021_010101",
        "lmstudio_qwen_qwen3.5-9b/react-lead-form/20261022_010101",
        "openrouter_openai_gpt-x/interest-cli-open-ended/20260902_010101"]
    # Old category and test folders are gone, .DS_Store and all
    assert not (runs / "lmstudio_qwen_qwen3.5-9b" / "geography").exists()
    for run_dir in dirs:
        meta = runrecord.read(run_dir)
        assert meta["run_path"] == run_dir.relative_to(runs).as_posix()
        assert bundle.record_problems("run", bundle.published_run(meta, "x")) == []
        for score in runrecord.scores(run_dir):
            assert score["score"] == before[meta["legacy_run_id"]]
            assert score["rubric_version"] == meta["local"]["legacy_meta"]["test"]["rubric_version"]
            assert bundle.record_problems("score", score) == []
        # The 2.x files stay, untouched
        assert (run_dir / "check_results.json").exists() == bool(runrecord.scores(run_dir))


def test_record_fields(tree):
    runs = tree / "runs"
    _migrate(runs)
    by_task = {runrecord.read(d)["task"]["id"] + "/" + d.name: runrecord.read(d) for d in runrecord.run_dirs(runs)}
    local = by_task["capitals-not-largest-city/20261021_010101"]
    assert local["task"] == {"id": "capitals-not-largest-city", "version": 1, "rubric_version": 2,
                             "content_hash": "c", "rubric_hash": "r", "alias": "GEOG-1"}
    # The quant name implies MLX
    assert local["model"]["format"] == "mlx" and local["model"]["variant_key"].endswith("|mlx|mlx-4bit")
    assert local["hardware"]["key"] == "m1-pro-32gb" and local["provenance"]["source"] == "crucible-migrate"
    cloud = by_task["interest-cli-open-ended/20260902_010101"]
    assert cloud["task"]["alias"] == "COD1" and cloud["harness"]["id"] == "opencode"
    assert cloud["hardware"] is None and cloud["endpoint"]["where"] == "cloud"
    grader = runrecord.scores(runs / "lmstudio_qwen_qwen3.5-9b/react-lead-form/20261022_010101")[0]
    assert grader["method"] == "hidden_tests" and grader["raw"] == {"passed": 3, "total": 4, "unit": "tests"}
    assert [i["passed"] for i in grader["items"] if i["type"] == "hidden_test"] == [True, True, False, True]
    assert grader["items"][-2]["detail"] == "boom"


def test_legacy_uuids_are_stable(tree, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(tree / "runs", copy)
    _migrate(tree / "runs")
    _migrate(copy)
    ours = sorted(runrecord.read(d)["run_uuid"] for d in runrecord.run_dirs(tree / "runs"))
    theirs = sorted(runrecord.read(d)["run_uuid"] for d in runrecord.run_dirs(copy))
    assert ours == theirs and len(set(ours)) == 4
    meta = runrecord.read(tree / "runs/lmstudio_qwen_qwen3.5-9b/capitals-not-largest-city/20261020_010101")
    assert meta["run_uuid"] == runrecord.legacy_run_uuid(
        "Ironwood", "lmstudio_qwen_qwen3.5-9b/geography/GEOG-1/20261020_010101")
    assert uuid.UUID(meta["run_uuid"]).version == 5
    # A hostname is used as its first label, lowercased: Ironwood.local, ironwood and Ironwood agree
    assert runrecord.legacy_run_uuid("Ironwood.local", "x") == runrecord.legacy_run_uuid("ironwood", "x")
    # No hostname recorded: --machine (default: this machine's name)
    old = runrecord.read(tree / "runs/openrouter_openai_gpt-x/interest-cli-open-ended/20260902_010101")
    assert old["run_uuid"] == runrecord.legacy_run_uuid("ironwood", "openrouter_openai_gpt-x/coding_build/COD1/20260902_010101")


def test_a_run_with_a_uuid_keeps_it(tree):
    run_dir = next((tree / "runs").rglob("20261020_010101"))
    meta = json.loads((run_dir / "meta.json").read_text())
    meta["run_uuid"] = "0b6f1d0c-5d5e-4f7f-9d2a-3c1f7b0e8a41"  # minted by 2.4.0
    (run_dir / "meta.json").write_text(json.dumps(meta))
    _migrate(tree / "runs")
    assert "0b6f1d0c-5d5e-4f7f-9d2a-3c1f7b0e8a41" in {runrecord.read(d)["run_uuid"] for d in runrecord.run_dirs(tree / "runs")}


def test_nested_archive_folders_migrate_too(tree):
    archive = tree / "runs-archive"
    _migrate(archive)
    (run_dir,) = [p.parent for p in archive.rglob("meta.json")]
    assert run_dir.relative_to(archive).as_posix() == "bad-runs/lmstudio_qwen_qwen3.5-9b/river-haiku-banned-words/20261023_010101"
    assert runrecord.invalid(run_dir)["reason"] == "stale server"


def test_unknown_ids_and_unfinished_runs_are_reported_and_left(tree):
    runs = tree / "runs"
    _legacy_run(runs, "m", "writing", "ZZZ-9", "20261024_010101")
    unfinished = runs / "m" / "writing" / "WRIT-3" / "20261025_010101"
    unfinished.mkdir(parents=True)
    (unfinished / "prompt.txt").write_text("x")
    m = _migrate(runs)
    assert any("unknown test ID ZZZ-9" in p for p in m.problems)
    assert any("no meta.json" in p for p in m.problems)
    assert (runs / "m" / "writing" / "ZZZ-9" / "20261024_010101" / "meta.json").exists() and unfinished.exists()


def test_format_2_export_reproduces_the_scores(tree):
    """The live dashboard reads format 2 until it switches: same runs, same IDs, same scores."""
    runs = tree / "runs"
    before = {}
    for cr in runs.rglob("check_results.json"):
        data = json.loads(cr.read_text())
        before[data["run_id"]] = data["scores"]["_overall"]
    _migrate(runs)
    exported = {r["run_id"]: r for r in exporter.export(runs)["runs"]}
    current_rv = workspace.load_task("capitals-not-largest-city")["rubric_version"]
    run = exported["lmstudio_qwen_qwen3.5-9b/geography/GEOG-1/20261020_010101"]
    assert run["test_id"] == "GEOG-1"
    assert run["check_score"] == (before[run["run_id"]] if current_rv == 1 else None)


def test_bundle_conversion_gives_the_same_uuids(tree, tmp_path):
    runs = tree / "runs"
    _migrate(runs)
    data = exporter.export(runs)
    data["source"] = {"machine": "ironwood"}
    path = tmp_path / "ironwood.json"
    path.write_text(json.dumps(data))
    published = tmp_path / "site" / "_data" / "crucible"
    bundle.publish(runs, published, bundle.default_outputs(published))
    converted = migrate.convert_bundle(path, published, bundle.default_outputs(published))
    assert converted.errors == [] and converted.counts["runs"] == 0  # every run is already there
    fresh = tmp_path / "fresh" / "_data" / "crucible"
    converted = migrate.convert_bundle(path, fresh, bundle.default_outputs(fresh))
    assert converted.errors == [] and converted.counts["runs"] == len(data["runs"])
    assert {p.stem for p in (fresh / "runs").rglob("*.json")} <= {p.stem for p in (published / "runs").rglob("*.json")}
    assert bundle.check_folder(fresh, bundle.default_outputs(fresh)) == []
