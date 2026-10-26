"""Test versions keep scores comparable: content and rubric changes must be declared."""
import json

import pytest
import yaml

from crucible import judge, versioning, workspace
from crucible.taxonomy import TEST_STATUSES, TIERS


def _entry(version=1, content="c1", rubric_version=1, rubric="r1"):
    return {"version": version, "content_hash": content, "prompt_hash": "p",
            "rubric_version": rubric_version, "rubric_hash": rubric}


class TestCheckLock:
    def test_clean(self):
        assert versioning.check_lock({"CODE-1": _entry()}, {"CODE-1": _entry()}) == []

    def test_content_changed_without_bump(self):
        (problem,) = versioning.check_lock({"CODE-1": _entry(content="c2")}, {"CODE-1": _entry()})
        assert "content changed" in problem and "bump version" in problem

    def test_rubric_changed_without_bump(self):
        (problem,) = versioning.check_lock({"CODE-1": _entry(rubric="r2")}, {"CODE-1": _entry()})
        assert "rubric changed" in problem

    def test_bump_without_change(self):
        (problem,) = versioning.check_lock({"CODE-1": _entry(version=2)}, {"CODE-1": _entry()})
        assert "without a content change" in problem

    def test_bump_with_change_needs_lock_update(self):
        (problem,) = versioning.check_lock({"CODE-1": _entry(version=2, content="c2")}, {"CODE-1": _entry()})
        assert "--update" in problem

    def test_new_and_removed_tests(self):
        problems = versioning.check_lock({"C9": _entry()}, {"CODE-1": _entry()})
        assert any("C9: not in the lock" in p for p in problems)
        assert any("CODE-1: in the lock but its prompt is gone" in p for p in problems)


class TestHashes:
    def test_rubric_edit_changes_only_rubric_hash(self):
        p = workspace.load_prompt("CODE-3")
        edited = {**p, "rubric": p["rubric"] + [{"criterion": "x", "max_score": 1}]}
        assert versioning.content_hash(edited) == versioning.content_hash(p)
        assert versioning.rubric_hash(edited) != versioning.rubric_hash(p)

    def test_prompt_edit_changes_content_hash(self):
        p = workspace.load_prompt("KNOW-1")
        assert versioning.content_hash({**p, "prompt": p["prompt"] + " Be brief."}) != versioning.content_hash(p)

    def test_repo_files_are_content(self, tmp_path, monkeypatch):
        repo = tmp_path / "demo"
        repo.mkdir()
        (repo / "app.js").write_text("one\n")
        monkeypatch.setattr(workspace, "REPOS_DIR", tmp_path)
        before = versioning.content_hash({"prompt": "x", "repo": "demo"})
        (repo / "app.js").write_text("two\n")
        assert versioning.content_hash({"prompt": "x", "repo": "demo"}) != before

    def test_line_endings_and_installed_deps_ignored(self, tmp_path, monkeypatch):
        repo = tmp_path / "demo"
        repo.mkdir()
        (repo / "app.js").write_bytes(b"one\n")
        monkeypatch.setattr(workspace, "REPOS_DIR", tmp_path)
        before = versioning.content_hash({"prompt": "x", "repo": "demo"})
        (repo / "app.js").write_bytes(b"one\r\n")
        (repo / "node_modules").mkdir()
        (repo / "node_modules" / "dep.js").write_text("installed")
        assert versioning.content_hash({"prompt": "x", "repo": "demo"}) == before


class TestRepoPrompts:
    """The real prompts: every test declares tier, versions and status, and matches the lock."""

    @pytest.mark.parametrize("test_id", workspace.all_test_ids())
    def test_declares_tier_and_versions(self, test_id):
        p = workspace.load_prompt(test_id)
        assert p.get("tier") in TIERS
        assert p.get("status") in TEST_STATUSES
        assert isinstance(p.get("version"), int) and p["version"] >= 1
        assert isinstance(p.get("rubric_version"), int) and p["rubric_version"] >= 1

    def test_lock_is_clean(self):
        assert versioning.check_lock() == []

    def test_release_lists_only_active_tests_at_current_versions(self):
        release = versioning.latest_release()
        assert release is not None
        for t in release["tests"]:
            p = workspace.load_prompt(t["id"])
            # A release is immutable; it may trail the prompts, but never point at a version that never existed
            assert t["version"] <= p["version"]
            assert t["tier"] in TIERS


class TestBackfill:
    def _run(self, tmp_path, prompt_text):
        run_dir = tmp_path / "runs" / "m" / "everyday" / "KNOW-1" / "20260101_000000"
        run_dir.mkdir(parents=True)
        (run_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        (run_dir / "meta.json").write_text(json.dumps({"test_id": "KNOW-1", "run_id": "m/everyday/KNOW-1/x"}))
        (run_dir / "agent_results.json").write_text(json.dumps({"scores": {"_overall": 9.0}}))
        return run_dir

    def test_matching_prompt_gets_version(self, tmp_path):
        run_dir = self._run(tmp_path, workspace.load_prompt("KNOW-1")["prompt"])
        lock = versioning.compute_lock()
        assert versioning.backfill_run(run_dir, lock) == f"v{lock['KNOW-1']['version']}"
        meta = json.loads((run_dir / "meta.json").read_text())
        assert meta["test"]["version"] == lock["KNOW-1"]["version"] and meta["test"]["backfilled"]
        scores = json.loads((run_dir / "agent_results.json").read_text())
        assert scores["rubric_version"] == lock["KNOW-1"]["rubric_version"]
        # Backfilled stamps can be redone (e.g. after a matching fix); real ones can't
        assert versioning.backfill_run(run_dir, lock) == f"v{lock['KNOW-1']['version']}"
        meta["test"] = {"version": 1}
        (run_dir / "meta.json").write_text(json.dumps(meta))
        assert versioning.backfill_run(run_dir, lock) == "already versioned"

    def test_direct_prompt_with_inlined_fixture_matches(self, tmp_path):
        p = workspace.load_prompt("TASK-1")
        sent = workspace.inline_fixtures(p["prompt"], workspace.fixture_names(p))
        run_dir = self._run(tmp_path, sent)
        meta = json.loads((run_dir / "meta.json").read_text())
        meta["test_id"] = "TASK-1"
        (run_dir / "meta.json").write_text(json.dumps(meta))
        assert versioning.backfill_run(run_dir, versioning.compute_lock()) == f"v{p['version']}"

    def test_different_prompt_is_not_comparable(self, tmp_path):
        run_dir = self._run(tmp_path, "An older wording of the question.")
        assert versioning.backfill_run(run_dir, versioning.compute_lock()) == "prompt differs"
        assert json.loads((run_dir / "meta.json").read_text())["test"]["version"] is None


# A test the judge scores: active, no checks bound to its criteria, no hidden grader
JUDGED = next(t for t in workspace.all_test_ids()
              if (p := workspace.load_prompt(t)).get("status") == "active"
              and not p.get("checks") and not p.get("grader"))


class TestJudge:
    def _run(self, tmp_path, version):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "meta.json").write_text(json.dumps(
            {"test_id": JUDGED, "run_id": f"m/x/{JUDGED}/x", "test": {"version": version}}))
        return run_dir

    @staticmethod
    def _full_marks(p):
        return {c["criterion"]: {"score": c["max_score"], "note": "ok"} for c in p["rubric"]}

    def test_saves_with_provenance(self, tmp_path):
        p = workspace.load_prompt(JUDGED)
        results = judge.save_agent_score(self._run(tmp_path, p["version"]),
                                         {"criteria": self._full_marks(p), "summary": "ok"})
        assert results["scores"]["_overall"] == 10.0
        assert results["rubric_version"] == p["rubric_version"]
        assert results["scorer"] == {"type": "agent", "model": judge.DEFAULT_JUDGE_MODEL,
                                     "prompt_version": judge.JUDGE_PROMPT_VERSION}

    def test_score_cap(self, tmp_path):
        p = workspace.load_prompt(JUDGED)
        results = judge.save_agent_score(self._run(tmp_path, p["version"]),
                                         {"criteria": self._full_marks(p), "score_cap": 3})
        assert results["scores"]["_overall"] == 3.0

    def test_rejects_wrong_criteria_and_ranges(self, tmp_path):
        p = workspace.load_prompt(JUDGED)
        run_dir = self._run(tmp_path, p["version"])
        with pytest.raises(judge.JudgeError, match="criterion mismatch"):
            judge.save_agent_score(run_dir, {"criteria": {"Made up": {"score": 1}}})
        too_high = {**self._full_marks(p), p["rubric"][0]["criterion"]: {"score": 99}}
        with pytest.raises(judge.JudgeError, match="outside"):
            judge.save_agent_score(run_dir, {"criteria": too_high})

    def test_refuses_run_from_another_test_version(self, tmp_path):
        p = workspace.load_prompt(JUDGED)
        with pytest.raises(judge.JudgeError, match="rerun"):
            judge.save_agent_score(self._run(tmp_path, p["version"] + 1), {"criteria": {}})


class TestWorkspaceIsolation:
    def test_workspace_lives_outside_the_checkout_and_moves_back(self, tmp_path):
        run_dir = tmp_path / "runs" / "m" / "coding_debug" / "CODE-2" / "ts"
        run_dir.mkdir(parents=True)
        ws = workspace.setup_workspace(run_dir, {"repo": "navbar-responsive"})
        assert workspace.REPO_ROOT not in ws.resolve().parents
        assert (run_dir / "workspace").is_symlink() and (run_dir / "workspace" / "index.html").exists()
        (ws / "edited.txt").write_text("agent work")
        workspace.finalize_workspace(run_dir)
        assert not (run_dir / "workspace").is_symlink()
        assert (run_dir / "workspace" / "edited.txt").read_text() == "agent work"
        assert not ws.exists()

    def test_leaks_into_the_checkout_are_found(self, tmp_path):
        from crucible import runner
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        grader = workspace.REPO_ROOT / "graders" / "forge" / "CODE-11" / "editorial.grader.test.ts"
        (run_dir / "stderr.txt").write_text(f"$ cat {grader}\nok\n")
        (run_dir / "stdout.txt").write_text(f"working in {run_dir.resolve()}/workspace\n")
        assert runner.find_leaks(run_dir) == [str(grader)]

    def test_clean_transcript_has_no_leaks(self, tmp_path):
        from crucible import runner
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "stdout.txt").write_text("all tests pass\n")
        assert runner.find_leaks(run_dir) == []

    def test_workspace_is_its_own_git_repo(self, tmp_path):
        import subprocess
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        ws = workspace.setup_workspace(run_dir, {"repo": "navbar-responsive"})
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ws, capture_output=True, text=True).stdout.strip()
        assert top and (ws.resolve() == type(ws)(top).resolve())
        log = subprocess.run(["git", "log", "--oneline"], cwd=ws, capture_output=True, text=True).stdout
        assert "Seeded workspace" in log
        # The seeded files are committed, so the agent's diff starts clean
        status = subprocess.run(["git", "status", "--porcelain"], cwd=ws, capture_output=True, text=True).stdout
        assert status == ""
