"""Test versions keep scores comparable: content and rubric changes must be declared."""
import json
import shutil
from pathlib import Path

import pytest
import yaml

from crucible import judge, versioning, workspace
from crucible.taxonomy import TASK_STATUSES, TIERS
from tests.records import run_meta


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
        assert any("CODE-1: in the lock but its task file is gone" in p for p in problems)


class TestHashes:
    def test_rubric_edit_changes_only_rubric_hash(self):
        p = workspace.load_task("CODE-3")
        edited = {**p, "rubric": p["rubric"] + [{"criterion": "x", "max_score": 1}]}
        assert versioning.content_hash(edited) == versioning.content_hash(p)
        assert versioning.rubric_hash(edited) != versioning.rubric_hash(p)

    def test_prompt_edit_changes_content_hash(self):
        p = workspace.load_task("KNOW-1")
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

    @pytest.mark.parametrize("test_id", workspace.all_task_ids())
    def test_declares_tier_and_versions(self, test_id):
        p = workspace.load_task(test_id)
        assert p.get("tier") in TIERS
        assert p.get("status") in TASK_STATUSES
        assert isinstance(p.get("version"), int) and p["version"] >= 1
        assert isinstance(p.get("rubric_version"), int) and p["rubric_version"] >= 1

    def test_lock_is_clean(self):
        assert versioning.check_lock() == []

    def test_every_task_has_a_valid_unique_slug_and_its_old_id(self):
        from crucible.taxonomy import validate_id
        seen: dict[str, str] = {}
        for task_id in workspace.all_task_ids():
            p = workspace.load_task(task_id)
            validate_id(p["id"])
            assert p["id"] == task_id, f"tasks/{task_id}.yaml declares id {p['id']}"
            assert p.get("name") and "test_id" not in p
            for alias in [task_id, *(p.get("aliases") or [])]:
                assert alias.lower() not in seen, f"{alias} names both {seen.get(alias.lower())} and {task_id}"
                seen[alias.lower()] = task_id


LEGACY_LOCK = json.loads((Path(__file__).parent / "fixtures" / "versions.lock.2.4.0.json").read_text(encoding="utf-8"))


def _legacy_rubric_hash(p: dict, grader_path: str) -> str:
    """rubric_hash as 2.4.0 computed it: the grader's folder path (tier/ID) was hashed too."""
    parts = [versioning._canonical({k: p.get(k) for k in versioning.RUBRIC_FIELDS}),
             grader_path.encode(), *versioning._tree_bytes(versioning.GRADERS_DIR / p["grader"])]
    if p.get("checks"):
        parts.append(versioning._canonical({"checks": p["checks"]}))
    if p.get("scoring"):
        parts.append(versioning._canonical({"scoring": p["scoring"]}))
    return versioning._sha(*parts)


def _skip_if_bumped_since_3_0_0(p: dict) -> None:
    """A task changed after the rename carries a version bump, which `crucible versions` checks instead."""
    old, now = LEGACY_LOCK[p["aliases"][0]], versioning.read_lock()[p["id"]]
    if (now["version"], now["rubric_version"]) > (old["version"], old["rubric_version"]):
        pytest.skip(f"{p['id']} changed after 3.0.0")


class TestRenameKeepsHashes:
    """3.0.0 renamed every task; no task's content or rubric changed, so no version moved."""

    @pytest.mark.parametrize("task_id", workspace.all_task_ids())
    def test_versions_and_content_hash_unchanged(self, task_id):
        p = workspace.load_task(task_id)
        _skip_if_bumped_since_3_0_0(p)
        old = LEGACY_LOCK[p["aliases"][0]]
        now = versioning.read_lock()[task_id]
        assert (now["version"], now["rubric_version"]) == (old["version"], old["rubric_version"])
        assert now["content_hash"] == old["content_hash"] and now["prompt_hash"] == old["prompt_hash"]

    @pytest.mark.parametrize("task_id", workspace.all_task_ids())
    def test_rubric_hash_unchanged_or_only_the_folder_name_left_it(self, task_id):
        p = workspace.load_task(task_id)
        _skip_if_bumped_since_3_0_0(p)
        old = LEGACY_LOCK[p["aliases"][0]]["rubric_hash"]
        now = versioning.read_lock()[task_id]["rubric_hash"]
        if not p.get("grader"):
            assert now == old
            return
        # A grader task hashed its folder path (forge/CODE-11), which held the old ID. Hashing the same
        # files under the old path reproduces the 2.4.0 hash, so nothing but the name changed.
        tier = "temper" if p["aliases"][0] == "CODE-16" else "forge"
        assert _legacy_rubric_hash(p, f"{tier}/{p['aliases'][0]}") == old
        assert now == versioning.rubric_hash(p)

    def test_new_rubric_hashes_map_one_to_one(self):
        lock = versioning.read_lock()
        # Tasks re-scored since 3.0.0 have a new rubric on purpose: two tasks that shared a rubric hash
        # (CODE-1 and CODE-1b, login-recovery and its repeat) may now differ
        unchanged = [t for t in lock if lock[t]["rubric_version"] == LEGACY_LOCK[workspace.load_task(t)["aliases"][0]]["rubric_version"]]
        pairs = {(LEGACY_LOCK[workspace.load_task(t)["aliases"][0]]["rubric_hash"], lock[t]["rubric_hash"]) for t in unchanged}
        # Each old hash became exactly one new hash, and no two old hashes became the same one
        assert len(pairs) == len({old for old, _ in pairs}) == len({new for _, new in pairs})


class TestTaskIdMap:
    MAP = json.loads((workspace.ID_MAP_PATH).read_text(encoding="utf-8"))

    def test_every_old_id_resolves_in_one_lookup(self):
        tasks = set(workspace.all_task_ids())
        for old, entry in self.MAP.items():
            assert entry["id"] in tasks, old
            assert workspace.resolve(old)[0] == entry["id"]

    def test_chained_ids(self):
        # C11 was renamed CODE-11 in 1.0.0 and editorial-review-workflow in 3.0.0
        assert self.MAP["C11"] == {"id": "editorial-review-workflow", "via": "CODE-11"}
        assert workspace.resolve("C11") == ("editorial-review-workflow", "C11")
        assert workspace.resolve("code-11") == ("editorial-review-workflow", "code-11")
        assert workspace.resolve("editorial-review-workflow") == ("editorial-review-workflow", None)
        with pytest.raises(KeyError):
            workspace.resolve("CODE-99")

    def test_every_task_is_in_the_map_under_its_alias(self):
        for task_id in workspace.all_task_ids():
            alias = workspace.load_task(task_id)["aliases"][0]
            assert self.MAP[alias]["id"] == task_id

    @pytest.mark.parametrize("bad", ["CODE-16", "react_lead_form", "-lead", "lead--form", "x" * 41,
                                     "react-lead-form-hard", "spark-capitals"])
    def test_slug_rules(self, bad):
        from crucible.taxonomy import validate_id
        with pytest.raises(ValueError):
            validate_id(bad)


# A task the judge scores: no checks bound to its criteria, no hidden grader. Suites since v3 score none this
# way, so it may be retired; the judge still scores any task's runs on request
JUDGED = next(t for t in workspace.all_task_ids()
              if not (p := workspace.load_task(t)).get("checks") and not p.get("grader"))


class TestJudge:
    def _run(self, tmp_path, version):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "meta.json").write_text(json.dumps(run_meta(JUDGED, version)))
        return run_dir

    @staticmethod
    def _full_marks(p):
        return {c["criterion"]: {"score": c["max_score"], "note": "ok"} for c in p["rubric"]}

    def test_saves_with_provenance(self, tmp_path):
        p = workspace.load_task(JUDGED)
        results = judge.save_agent_score(self._run(tmp_path, p["version"]),
                                         {"criteria": self._full_marks(p), "summary": "ok"})
        assert results["scores"]["_overall"] == 10.0
        assert results["rubric_version"] == p["rubric_version"]
        assert results["scorer"] == {"type": "agent", "model": judge.DEFAULT_JUDGE_MODEL,
                                     "prompt_version": judge.JUDGE_PROMPT_VERSION}

    def test_score_cap(self, tmp_path):
        p = workspace.load_task(JUDGED)
        results = judge.save_agent_score(self._run(tmp_path, p["version"]),
                                         {"criteria": self._full_marks(p), "score_cap": 3})
        assert results["scores"]["_overall"] == 3.0

    def test_rejects_wrong_criteria_and_ranges(self, tmp_path):
        p = workspace.load_task(JUDGED)
        run_dir = self._run(tmp_path, p["version"])
        with pytest.raises(judge.JudgeError, match="criterion mismatch"):
            judge.save_agent_score(run_dir, {"criteria": {"Made up": {"score": 1}}})
        too_high = {**self._full_marks(p), p["rubric"][0]["criterion"]: {"score": 99}}
        with pytest.raises(judge.JudgeError, match="outside"):
            judge.save_agent_score(run_dir, {"criteria": too_high})

    def test_refuses_run_from_another_test_version(self, tmp_path):
        p = workspace.load_task(JUDGED)
        with pytest.raises(judge.JudgeError, match="rerun"):
            judge.save_agent_score(self._run(tmp_path, p["version"] + 1), {"criteria": {}})


class TestWorkspaceIsolation:
    def test_workspace_lives_outside_the_checkout_and_moves_back(self, tmp_path):
        run_dir = tmp_path / "runs" / "m" / "responsive-navbar-open-ended" / "ts"
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
        grader = workspace.REPO_ROOT / "graders" / "editorial-review-workflow" / "editorial.grader.test.ts"
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


def test_calendar_dataset_and_server_are_part_of_the_content_hash(tmp_path, monkeypatch):
    """A dataset or server edit is a task content change: it must show up as drift."""
    prompt = {"prompt": "p", "mcp_servers": ["mock-calendar:spark"]}
    base = versioning.content_hash(prompt)
    assert versioning.content_hash({**prompt, "mcp_servers": ["mock-calendar:pair"]}) != base
    fixtures = tmp_path / "fixtures"
    shutil.copytree(workspace.FIXTURES_DIR / "mock-calendar", fixtures / "mock-calendar")
    monkeypatch.setattr(workspace, "FIXTURES_DIR", fixtures)
    assert versioning.content_hash(prompt) == base
    spark = fixtures / "mock-calendar" / "spark.json"
    spark.write_text(spark.read_text().replace("Design review", "Design sync"))
    assert versioning.content_hash(prompt) != base
