import pytest


@pytest.fixture(autouse=True)
def isolated_workspaces(tmp_path_factory, monkeypatch):
    """Agent workspaces go to a temp dir in tests, never the real ~/.crucible/workspaces."""
    monkeypatch.setenv("CRUCIBLE_WORKSPACES", str(tmp_path_factory.mktemp("workspaces")))
