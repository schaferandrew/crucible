import pytest


@pytest.fixture(autouse=True)
def isolated_workspaces(tmp_path_factory, monkeypatch):
    """Agent workspaces go to a temp dir in tests, never the real ~/.crucible/workspaces."""
    monkeypatch.setenv("CRUCIBLE_WORKSPACES", str(tmp_path_factory.mktemp("workspaces")))


@pytest.fixture(autouse=True)
def isolated_machine_id(tmp_path_factory, monkeypatch):
    """Tests mint their machine ID in a temp dir, never the real ~/.crucible/machine.json."""
    monkeypatch.setenv("CRUCIBLE_MACHINE_FILE", str(tmp_path_factory.mktemp("machine") / "machine.json"))


TEST_DEVICES = """\
devices:
  Ironwood: {cpu: Apple M1 Pro, gpu: null, ram_gb: 32}
  Whitehall: {cpu: AMD Ryzen 7 7700, gpu: NVIDIA RTX 5070 Ti 16GB, ram_gb: 32, aliases: [desktop-d2j5pm9]}
  Duskfall: {cpu: Apple M5 Pro, gpu: null, ram_gb: 48}
"""


@pytest.fixture(autouse=True)
def isolated_devices(tmp_path_factory, monkeypatch):
    """Tests read a devices file of known machines, never the real ~/.crucible/devices.yaml."""
    path = tmp_path_factory.mktemp("devices") / "devices.yaml"
    path.write_text(TEST_DEVICES, encoding="utf-8")
    monkeypatch.setenv("CRUCIBLE_DEVICES_FILE", str(path))
    return path
