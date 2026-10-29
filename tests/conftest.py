import pytest


@pytest.fixture(autouse=True)
def isolated_workspaces(tmp_path_factory, monkeypatch):
    """Agent workspaces go to a temp dir in tests, never the real ~/.crucible/workspaces."""
    monkeypatch.setenv("CRUCIBLE_WORKSPACES", str(tmp_path_factory.mktemp("workspaces")))


@pytest.fixture(autouse=True)
def isolated_machine_id(tmp_path_factory, monkeypatch):
    """Tests mint their machine ID in a temp dir, never the real ~/.crucible/machine.json."""
    monkeypatch.setenv("CRUCIBLE_MACHINE_FILE", str(tmp_path_factory.mktemp("machine") / "machine.json"))
