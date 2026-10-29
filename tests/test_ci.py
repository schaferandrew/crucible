"""The two-track release check CI runs on pull requests (crucible/ci.py)."""
from crucible import ci

LOG = "# Changelog\n\n## 3.1.0 (2026-11-20)\n\n- x\n\n## 3.0.0 (2026-10-29)\n"


def test_tool_change_needs_a_bump_and_a_changelog_entry():
    assert ci.problems(["crucible/runner.py"], [], "3.0.0", "3.1.0", LOG, []) == []
    (problem,) = ci.problems(["crucible/runner.py"], [], "3.0.0", "3.0.0", LOG, [])
    assert "version bump" in problem
    (problem,) = ci.problems(["tests/test_x.py"], [], "3.0.0", "3.2.0", LOG, [])
    assert "## 3.2.0" in problem
    (problem,) = ci.problems(["pyproject.toml"], [], "3.0.0", "3.0.0", LOG, [])


def test_task_change_needs_a_suite_changelog_entry_and_no_bump():
    assert ci.problems(["tasks/fire-truck-color.yaml"], [], "3.0.0", "3.0.0", LOG, ["- Clarified the prompt."]) == []
    (problem,) = ci.problems(["graders/react-lead-form/x.ts"], [], "3.0.0", "3.0.0", LOG, ["", "  "])
    assert "SUITE_CHANGELOG.md" in problem


def test_a_pr_on_both_tracks_needs_both():
    found = ci.problems(["crucible/a.py", "repos/demo/app.js"], [], "3.0.0", "3.0.0", LOG, [])
    assert len(found) == 2


def test_suite_files_may_be_added_but_not_edited():
    assert ci.problems(["suites/v2.yaml", "SUITE_CHANGELOG.md"], [], "3.0.0", "3.0.0", LOG, []) == []
    (problem,) = ci.problems(["suites/v1.yaml"], ["suites/v1.yaml"], "3.0.0", "3.0.0", LOG, [])
    assert "immutable" in problem


def test_docs_only_needs_nothing():
    assert ci.problems(["README.md", "docs/versioning.md", "AGENTS.md"], ["README.md"], "3.0.0", "3.0.0", LOG, []) == []


def test_version_is_read_from_pyproject():
    assert ci.version_of('[project]\nname = "crucible"\nversion = "3.0.0"\n') == "3.0.0"
