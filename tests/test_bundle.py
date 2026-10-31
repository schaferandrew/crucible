from crucible import bundle, exporter


def test_export_is_a_valid_bundle(tmp_path):
    data = exporter.export(tmp_path)  # no runs: still the full shape
    assert bundle.problems(data) == []


def test_problems_name_the_bad_field(tmp_path):
    data = exporter.export(tmp_path)
    data["runs"] = [{"run_id": "m/c/WRIT-2/1", "test_id": "WRIT-2", "harness": "direct", "model": "x/y",
                     "started_at": "2026-10-26", "counts": "yes", "check_score": True}]
    found = bundle.problems(data)
    assert any("runs[0].counts" in p for p in found)
    assert any("runs[0].check_score" in p for p in found)
    del data["tests"]
    assert "$: missing 'tests'" in bundle.problems(data)


def test_hidden_test_scoring_and_contract_cap(tmp_path):
    import json
    from crucible import checks
    prompt = {"version": 1, "rubric_version": 1, "rubric": [
        {"criterion": "Contract", "max_score": 3, "hidden_tests": "contract"},
        {"criterion": "Existing tests still pass", "max_score": 1, "hidden_tests": "existing"},
        {"criterion": "Contract suite untouched", "max_score": 1, "hidden_tests": "contract_unchanged", "cap_if_failed": 4},
    ]}
    grader = {"tests": [{"file": "a.grader.test.ts", "group": "contract", "name": n, "passed": p, "error": None}
                        for n, p in [("one", True), ("two", True), ("three", False)]],
              "existing": {"passed": True}, "contract_unchanged": True, "regression": {"passed": False}}
    from tests.records import run_meta
    (tmp_path / "meta.json").write_text(json.dumps(run_meta("editorial-review-workflow")))
    record = checks.save_check_score(tmp_path, prompt, [], grader)
    assert record["scores"]["Contract"] == 2.0          # 2 of 3 hidden tests
    assert record["scores"]["_overall"] == 8.0          # 4 of 5 points
    grader["contract_unchanged"] = False
    record = checks.save_check_score(tmp_path, prompt, [], grader)
    assert record["scores"]["_overall"] == 4.0 and record["capped_at"] == 4  # 6.0 capped


# --------------------------------------------------------------------------
# Format 3: crucible publish
# --------------------------------------------------------------------------

def _runs(tmp_path, n=2):
    from crucible import runrecord, workspace
    from tests.records import run_meta, write_run
    p = workspace.load_task("capitals-not-largest-city")
    runs = tmp_path / "runs"
    for i in range(n):
        meta = run_meta(p["id"], p["version"], p["rubric_version"], run_uuid=f"00000000-0000-4000-8000-00000000000{i}",
                        run_path=f"lmstudio_m/{p['id']}/2026010{i}_000000")
        run_dir = write_run(runs / meta["run_path"], meta, "Australia: Canberra ✅ 🎉")
        legacy = {"scorer": {"type": "checks"}, "rubric_version": p["rubric_version"], "scores": {"_overall": 6.0},
                  "criteria": [{"criterion": "Capitals", "max_score": 6, "score": 6, "detail": "all six"},
                               {"criterion": "No big-city traps", "max_score": 4, "score": 0, "detail": "Sydney"}],
                  "checks": [{"id": "capitals", "type": "required_patterns", "passed": True, "detail": "all six"}]}
        runrecord.write_score(run_dir, runrecord.score_from_checks(legacy, meta["run_uuid"], rubric=p["rubric"]))
    return runs


def _tree(folder):
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_publish_twice_adds_nothing_the_second_time(tmp_path):
    runs, to, outputs = _runs(tmp_path), tmp_path / "site" / "_data" / "crucible", tmp_path / "site" / "crucible-data" / "outputs"
    first = bundle.publish(runs, to, outputs)
    assert first.errors == [] and first.counts["runs"] == 2 and first.counts["scores"] == 2 and first.counts["catalogs"] >= 1
    before = _tree(tmp_path / "site")
    second = bundle.publish(runs, to, outputs)
    assert second.counts == {"runs": 0, "scores": 0, "status": 0, "catalogs": 0, "outputs": 0, "invalid": 0}
    assert _tree(tmp_path / "site") == before
    assert sorted(p.name for p in (to / "runs" / "2026-01").iterdir()) == [
        "00000000-0000-4000-8000-000000000000.json", "00000000-0000-4000-8000-000000000001.json"]
    assert bundle.check_folder(to, outputs) == []


def test_published_records_stay_local_free_and_plain_utf8(tmp_path):
    import json
    runs, to = _runs(tmp_path, 1), tmp_path / "site" / "_data" / "crucible"
    bundle.publish(runs, to, bundle.default_outputs(to))
    (path,) = (to / "runs" / "2026-01").iterdir()
    record = json.loads(path.read_text(encoding="utf-8"))
    assert "local" not in record and record["output_ref"] == f"outputs/{record['run_uuid']}.txt"
    assert record["provenance"]["content_hash"].startswith("sha256:")
    output = (tmp_path / "site" / "crucible-data" / "outputs" / f"{record['run_uuid']}.txt").read_text(encoding="utf-8")
    assert "🎉" in output
    (score_path,) = (to / "scores" / "2026-01").iterdir()
    assert score_path.name == f"{record['run_uuid']}.r{json.loads(score_path.read_text())['rubric_version']}.checks.json"
    assert "checked_text" not in json.loads(score_path.read_text())


def test_publish_adds_new_runs_and_scores_but_never_rewrites(tmp_path):
    import json
    from crucible import runrecord
    runs, to = _runs(tmp_path, 1), tmp_path / "site" / "_data" / "crucible"
    outputs = bundle.default_outputs(to)
    bundle.publish(runs, to, outputs)
    (run_dir,) = runrecord.run_dirs(runs)
    # A rescore at a new rubric version and a later invalidation are new records, not edits
    score = runrecord.scores(run_dir)[0]
    runrecord.write_score(run_dir, {**score, "rubric_version": score["rubric_version"] + 1, "score": 10.0})
    runrecord.add_status(run_dir, score["run_uuid"], invalid={"reason": "stale server"})
    meta = json.loads((run_dir / "meta.json").read_text())
    meta["elapsed_s"] = 99.0  # an edited local record is not republished
    (run_dir / "meta.json").write_text(json.dumps(meta))
    pub = bundle.publish(runs, to, outputs)
    assert (pub.counts["runs"], pub.counts["scores"], pub.counts["status"]) == (0, 1, 1)
    (published,) = (to / "runs" / "2026-01").iterdir()
    assert json.loads(published.read_text())["elapsed_s"] == 1.0
    assert len(json.loads((to / "status" / f"{score['run_uuid']}.json").read_text())) == 1
    assert bundle.check_folder(to, outputs) == []


def test_check_finds_edits_and_bad_files(tmp_path):
    import json
    runs, to = _runs(tmp_path, 1), tmp_path / "site" / "_data" / "crucible"
    outputs = bundle.default_outputs(to)
    bundle.publish(runs, to, outputs)
    (path,) = (to / "runs" / "2026-01").iterdir()
    record = json.loads(path.read_text())
    (outputs / f"{record['run_uuid']}.txt").write_text("a better answer", encoding="utf-8")
    assert any("content hash" in p for p in bundle.check_folder(to, outputs))
    (outputs / f"{record['run_uuid']}.txt").write_text("Australia: Canberra ✅ 🎉", encoding="utf-8")
    record["task"]["version"] = "one"
    path.write_text(json.dumps(record))
    found = bundle.check_folder(to, outputs)
    assert any("task.version" in p for p in found) and any("content hash" in p for p in found)


def test_publish_demotes_the_previous_suite_when_a_new_one_is_cut(tmp_path):
    import json
    from crucible import suites
    names = suites.names()
    if len(names) < 2:
        return
    to = tmp_path / "crucible"
    bundle.publish(_runs(tmp_path, 1), to, bundle.default_outputs(to))
    previous = to / "catalog" / f"{names[-2]}.json"
    stale = json.loads(previous.read_text())
    stale["suite"]["status"] = "current"
    previous.write_text(json.dumps(stale))
    bundle.publish(_runs(tmp_path, 1), to, bundle.default_outputs(to))
    assert json.loads(previous.read_text())["suite"]["status"] == "past"
    assert json.loads((to / "catalog" / f"{names[-1]}.json").read_text())["suite"]["status"] == "current"


def test_catalog_describes_the_suite(tmp_path):
    from crucible import suites, workspace
    data = bundle.catalog(suites.names()[-1])
    assert bundle.record_problems("catalog", data) == []
    assert data["format_version"] == 3 and data["suite"]["status"] == "current"
    tasks = {t["id"]: t for t in data["tasks"]}
    assert set(tasks) == set(workspace.all_task_ids())
    active = [t for t in data["tasks"] if t["status"] == "active"]
    assert active and all(t["weight"] for t in active)
    assert all(t["weight"] is None for t in data["tasks"] if t["status"] != "active")
    assert tasks["react-lead-form"]["aliases"] == ["CODE-16"]
    assert {t["role"] for t in data["tiers"]} == {"gate", "headline", "stretch"}


def test_publish_refuses_runs_from_before_3(tmp_path):
    import json
    import pytest
    legacy = tmp_path / "runs" / "m" / "everyday" / "KNOW-1" / "20260101_000000"
    legacy.mkdir(parents=True)
    (legacy / "meta.json").write_text(json.dumps({"run_id": "m/everyday/KNOW-1/20260101_000000"}))
    with pytest.raises(SystemExit, match="crucible migrate"):
        bundle.publish(tmp_path / "runs", tmp_path / "to", tmp_path / "out")


def test_publish_derives_decode_speed_for_a_run_made_before_it_was_recorded(tmp_path):
    import json
    from crucible import runrecord
    from crucible.agents import pi as pi_agent
    from tests.records import run_meta, write_run
    from crucible import workspace
    runs = tmp_path / "runs"
    p = workspace.load_task("interest-calculator-cli")  # agentic, so pi is its harness
    meta = run_meta(p["id"], p["version"], p["rubric_version"], harness="pi", run_path=f"lmstudio_m/{p['id']}/20260101_000000")
    run_dir = write_run(runs / meta["run_path"], meta, "Done.")
    (run_dir / pi_agent.TIMING_FILENAME).write_text(
        json.dumps({"request_start": 0, "first_token": 500, "end": 2500}) + "\n", encoding="utf-8")
    sessions = run_dir / pi_agent.SESSION_DIRNAME
    sessions.mkdir()
    (sessions / "s.jsonl").write_text(json.dumps(
        {"type": "message", "message": {"role": "assistant", "usage": {"output": 40}, "content": []}}) + "\n", encoding="utf-8")
    before = (run_dir / "meta.json").read_bytes()
    to, outputs = tmp_path / "site" / "_data" / "crucible", tmp_path / "site" / "crucible-data" / "outputs"
    pub = bundle.publish(runs, to, outputs)
    published = json.loads(next((to / "runs").glob("*/*.json")).read_text(encoding="utf-8"))
    assert pub.errors == [] and published["metrics"]["output_tokens_per_s"] == 20.0  # 40 tokens over 2.0 s
    assert (run_dir / "meta.json").read_bytes() == before                           # the run record is untouched
    assert bundle.check_folder(to, outputs) == []


def test_publish_adds_no_decode_speed_when_nothing_was_timed(tmp_path):
    import json
    runs = _runs(tmp_path, 1)
    to, outputs = tmp_path / "site" / "_data" / "crucible", tmp_path / "site" / "crucible-data" / "outputs"
    bundle.publish(runs, to, outputs)
    published = json.loads(next((to / "runs").glob("*/*.json")).read_text(encoding="utf-8"))
    assert "output_tokens_per_s" not in published["metrics"]


def test_publish_skips_runs_through_a_harness_their_mode_does_not_use(tmp_path):
    from crucible import runrecord, workspace
    from tests.records import run_meta, write_run
    runs, to = _runs(tmp_path, 1), tmp_path / "site" / "_data" / "crucible"
    p = workspace.load_task("capitals-not-largest-city")
    for i, harness in enumerate(("opencode", "pool")):
        meta = run_meta(p["id"], p["version"], p["rubric_version"], harness=harness,
                        run_uuid=f"00000000-0000-4000-8000-00000000001{i}", run_path=f"lmstudio_m/{p['id']}/2026010{i}_120000")
        write_run(runs / meta["run_path"], meta, "Australia: Canberra")
    pub = bundle.publish(runs, to, bundle.default_outputs(to))
    assert pub.errors == [] and pub.counts["runs"] == 1 and len(pub.skipped) == 2
    assert "not opencode" in pub.skipped[0] and "not pool" in pub.skipped[1]
    # Skipped, not deleted: the runs are still there to rescore or publish once they can count
    assert len(runrecord.run_dirs(runs)) == 3
