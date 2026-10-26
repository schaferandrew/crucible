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
    (tmp_path / "meta.json").write_text(json.dumps({"run_id": "m/c/CODE-11/1", "test_id": "CODE-11"}))
    record = checks.save_check_score(tmp_path, prompt, [], grader)
    assert record["scores"]["Contract"] == 2.0          # 2 of 3 hidden tests
    assert record["scores"]["_overall"] == 8.0          # 4 of 5 points
    grader["contract_unchanged"] = False
    record = checks.save_check_score(tmp_path, prompt, [], grader)
    assert record["scores"]["_overall"] == 4.0 and record["capped_at"] == 4  # 6.0 capped


def test_published_bundle_has_no_escaped_emoji(tmp_path, monkeypatch):
    # Jekyll reads data files with a YAML parser that rejects \ud83d-style escapes
    import json
    import sys
    from crucible import bundle
    real_export = bundle.exporter.export
    monkeypatch.setattr(bundle.exporter, "export", lambda runs: {**real_export(tmp_path / "none"), "note": "done ✅ 🎉"})
    (tmp_path / "none").mkdir()
    monkeypatch.setattr(sys, "argv", ["crucible publish", "--to", str(tmp_path / "out"), "--name", "t"])
    bundle.main()
    text = (tmp_path / "out" / "t.json").read_text(encoding="utf-8")
    assert "🎉" in text and "\\ud83c" not in text
    assert json.loads(text)["note"] == "done ✅ 🎉"
