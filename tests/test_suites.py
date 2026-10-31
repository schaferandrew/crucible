"""Suites: cut, patch and verify, on a copy of the tasks so the real ones never change."""
import json
import shutil

import pytest
import yaml

from crucible import suites, versioning, workspace


def test_repo_suite_holds():
    assert suites.verify() == []
    latest = suites.latest()
    assert latest["suite"] == suites.names()[-1]
    statuses = {t: workspace.load_task(t)["status"] for t in workspace.all_task_ids()}
    assert {t["id"] for t in latest["tasks"]} == {t for t, s in statuses.items() if s == "active"}


def test_v1_comes_from_release_2026_11():
    v1 = suites.load("v1")
    assert v1["from_release"] == "2026.11" and v1["cut_at"] == "2026-10-28"
    # Pins today's active tasks, not the stale release; the release is kept for the record
    assert {"grade-palindrome-function", "grade-two-sentence-summary"} <= set(suites.pins(v1))
    assert v1["release_2026_11"]["category_weights"]["coding_repo"] == 0.15
    assert abs(sum(v1["category_weights"].values()) - 1) < 1e-9
    assert {t["alias"] for t in v1["release_2026_11"]["tests"]} >= {"CODE-1", "WRIT-1a"}


def test_runs_count_in_suites_by_task_version():
    pin = suites.pins(suites.load("v1"))["fire-truck-color"]
    assert "v1" in suites.counts_in("fire-truck-color", pin["version"])
    assert suites.counts_in("fire-truck-color", pin["version"] + 1) == []
    assert suites.counts_in("recipe-and-discount", 1) == []  # retired before any suite pinned it


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A copy of tasks/, suites/ and SUITE_CHANGELOG.md that cut and patch may change."""
    tasks = tmp_path / "tasks"
    shutil.copytree(workspace.TASKS_DIR, tasks)
    shutil.copytree(suites.SUITES_DIR, tmp_path / "suites")
    changelog = tmp_path / "SUITE_CHANGELOG.md"
    changelog.write_text("# Suite changelog\n\n## Unreleased\n\n- Promoted recipe-and-discount.\n\n"
                         "## Suite v1 (2026-10-24)\n\nThe first suite.\n", encoding="utf-8")
    monkeypatch.setattr(workspace, "TASKS_DIR", tasks)
    monkeypatch.setattr(versioning, "LOCK_PATH", tasks / "versions.lock.json")
    monkeypatch.setattr(suites, "SUITES_DIR", tmp_path / "suites")
    monkeypatch.setattr(suites, "CHANGELOG_PATH", changelog)
    # Every real task has been promoted or retired; the tests promote one that no suite pins
    _edit(tmp_path, "recipe-and-discount", status="provisional")
    return tmp_path


def _names():
    """(latest suite, the next major, the one after): the tests cut and patch relative to the repo's suites."""
    latest = suites.names()[-1]
    major = int(latest[1:].split(".")[0])
    return latest, f"v{major + 1}", f"v{major + 2}"


def _edit(sandbox, task_id, **changes):
    path = sandbox / "tasks" / f"{task_id}.yaml"
    data = yaml.safe_load(path.read_text())
    data.update(changes)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def test_cut_promotes_retires_and_closes_the_changelog(sandbox):
    _, nxt, after = _names()
    path = suites.cut(nxt, promote=["MATH-1"], retire=["seating-logic-puzzle"], date="2026-11-15", check_graders=False)
    assert path == sandbox / "suites" / f"{nxt}.yaml"
    v2 = yaml.safe_load(path.read_text())
    pinned = suites.pins(v2)
    assert "recipe-and-discount" in pinned and "seating-logic-puzzle" not in pinned
    assert workspace.load_task("recipe-and-discount")["status"] == "active"
    assert workspace.load_task("seating-logic-puzzle")["status"] == "retired"
    lock = versioning.read_lock()
    assert pinned["recipe-and-discount"]["content_hash"] == lock["recipe-and-discount"]["content_hash"]
    by_category = {}
    for t in v2["tasks"]:
        by_category.setdefault(t["category"], []).append(t["weight"])
    assert all(abs(sum(w) - v2["category_weights"][c]) < 1e-5 for c, w in by_category.items())
    text = (sandbox / "SUITE_CHANGELOG.md").read_text()
    assert f"## Unreleased\n\n## Suite {nxt} (2026-11-15)\n\n- Promoted recipe-and-discount." in text
    assert suites.verify() == []
    # Suites are immutable and numbered in order
    with pytest.raises(ValueError, match=f"next suite is {after}"):
        suites.cut(f"v{int(after[1:]) + 1}", date="2026-11-16", check_graders=False)


def test_cut_refuses_without_a_changelog_entry_or_with_a_dirty_lock(sandbox):
    nxt = _names()[1]
    (sandbox / "SUITE_CHANGELOG.md").write_text("# Suite changelog\n\n## Unreleased\n\n## Suite v1 (x)\n")
    with pytest.raises(ValueError, match="Nothing under"):
        suites.cut(nxt, promote=["MATH-1"], check_graders=False)
    assert not (sandbox / "suites" / f"{nxt}.yaml").exists()
    (sandbox / "SUITE_CHANGELOG.md").write_text("# Suite changelog\n\n## Unreleased\n\n- x\n")
    original = workspace.load_task("recipe-and-discount")["prompt"]
    _edit(sandbox, "recipe-and-discount", prompt="A different haiku.")
    with pytest.raises(ValueError, match="lock isn't clean"):
        suites.cut(nxt, promote=["MATH-1"], check_graders=False)
    with pytest.raises(ValueError, match="not provisional"):
        _edit(sandbox, "recipe-and-discount", prompt=original)
        suites.cut(nxt, promote=["fire-truck-color"], check_graders=False)


def test_verify_catches_unbumped_changes_and_status_edits(sandbox):
    latest = _names()[0]
    _edit(sandbox, "fire-truck-color", prompt="What colour is a fire truck in Ireland?")
    versioning.write_lock()  # someone updated the lock but forgot the version bump
    problems = suites.verify()
    assert any(f"fire-truck-color: content changed since suite {latest}" in p for p in problems)
    _edit(sandbox, "recipe-and-discount", status="active")
    _edit(sandbox, "names-for-one-character", status="retired")
    problems = suites.verify()
    assert any(f"recipe-and-discount: active but not in suite {latest}" in p for p in problems)
    assert any(f"names-for-one-character: pinned in suite {latest} but retired" in p for p in problems)


def test_a_version_bump_is_allowed_after_a_suite(sandbox):
    p = workspace.load_task("fire-truck-color")
    _edit(sandbox, "fire-truck-color", prompt="What colour is a fire truck in Ireland?", version=p["version"] + 1)
    versioning.write_lock()
    assert suites.verify() == []


def test_patch_pins_rubric_fixes_only(sandbox):
    # Tasks converted since the latest suite wait for the next cut with a content bump, which a patch refuses: pin them
    # in the sandbox as already re-cut, so this test only sees rubric fixes
    latest = _names()[0]
    v1 = sandbox / "suites" / f"{latest}.yaml"
    suite = yaml.safe_load(v1.read_text())
    lock = versioning.read_lock()
    for pin in suite["tasks"]:
        if lock[pin["id"]]["version"] != pin["version"]:
            pin.update({k: lock[pin["id"]][k] for k in ("version", "content_hash")})
    v1.write_text(yaml.safe_dump(suite, sort_keys=False, allow_unicode=True))
    p = workspace.load_task("fire-truck-color")
    rubric = [{**item, "description": item["description"] + " (clarified)"} for item in p["rubric"]]
    _edit(sandbox, "fire-truck-color", rubric=rubric, rubric_version=p["rubric_version"] + 1)
    versioning.write_lock()
    assert suites.verify() == []
    lock = versioning.read_lock()
    # The repo's own rubric fixes since the latest suite (if any) are pinned too
    fixed = sorted(t for t, pin in suites.pins(suites.latest()).items() if lock[t]["rubric_version"] > pin["rubric_version"])
    path, bumped = suites.patch(date="2026-11-20")
    assert path.name == f"{latest}.1.yaml" and "fire-truck-color" in bumped and sorted(bumped) == fixed
    v11 = yaml.safe_load(path.read_text())
    assert v11["version"] == f"{latest[1:]}.1" and "from_release" not in v11
    pin = suites.pins(v11)["fire-truck-color"]
    assert pin["rubric_version"] == p["rubric_version"] + 1 and pin["version"] == p["version"]
    assert suites.names(sandbox / "suites")[-1] == f"{latest}.1"
    assert f"## Suite {latest}.1 (2026-11-20)" in (sandbox / "SUITE_CHANGELOG.md").read_text()
    with pytest.raises(ValueError, match="Nothing under"):
        suites.patch()  # the changelog section was used up by v1.1


def test_patch_refuses_content_changes(sandbox):
    p = workspace.load_task("fire-truck-color")
    _edit(sandbox, "fire-truck-color", prompt="What colour is a fire truck in Ireland?", version=p["version"] + 1)
    versioning.write_lock()
    with pytest.raises(ValueError, match="needs a new suite"):
        suites.patch()
