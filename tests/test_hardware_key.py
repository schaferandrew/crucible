"""The hardware key: the accelerator that ran the weights, plus its memory (audit section 6)."""
import pytest

from crucible import hardware


@pytest.mark.parametrize("cpu, gpu, ram_gb, key", [
    ("Apple M1 Pro", None, 32.0, "m1-pro-32gb"),
    ("M1 Pro", None, 32, "m1-pro-32gb"),                      # same chip, same key
    ("Apple M5 Pro", None, 48.0, "m5-pro-48gb"),
    ("AMD Ryzen 7 7700", "NVIDIA RTX 5070 Ti 16GB", 32.0, "rtx-5070-ti-16gb"),
    ("AMD Ryzen 7 7700", "NVIDIA GeForce RTX 5070 Ti, 16303 MiB", 32.0, "rtx-5070-ti-16gb"),  # nvidia-smi
    ("AMD Ryzen 9", "NVIDIA GeForce RTX 3090, 24576 MiB\nNVIDIA GeForce RTX 3090, 24576 MiB", 64.0,
     "2x-rtx-3090-24gb"),
    ("AMD Ryzen 9", "NVIDIA GeForce RTX 3090, 24576 MiB\nNVIDIA GeForce RTX 4090, 24564 MiB", 64.0,
     "rtx-4090-24gb+rtx-3090-24gb"),
    ("AMD Ryzen 9", "NVIDIA GeForce RTX 4060, 8188 MiB\nNVIDIA GeForce RTX 3090, 24576 MiB", 64.0,
     "rtx-3090-24gb+rtx-4060-8gb"),                             # mixed: most VRAM first
    ("AMD Ryzen 7 7700", None, 31.8, "cpu-ryzen-7-7700-32gb"),
    ("AMD Ryzen 7 7700 8-Core Processor", None, 32.0, "cpu-ryzen-7-7700-32gb"),
    ("Intel(R) Core(TM) i7-9700K CPU @ 3.60GHz", None, 16.0, "cpu-i7-9700k-16gb"),
    (None, None, 32.0, None),
])
def test_key(cpu, gpu, ram_gb, key):
    assert hardware.key(cpu, gpu, ram_gb) == key


def test_listed_machines_have_their_keys():
    whitehall, ironwood = hardware.specs("Whitehall"), hardware.specs("Ironwood")
    duskfall = hardware.specs("Duskfall")
    assert hardware.key(whitehall["cpu"], whitehall["gpu"], whitehall["ram_gb"]) == "rtx-5070-ti-16gb"
    assert hardware.key(ironwood["cpu"], ironwood["gpu"], ironwood["ram_gb"]) == "m1-pro-32gb"
    assert hardware.key(duskfall["cpu"], duskfall["gpu"], duskfall["ram_gb"]) == "m5-pro-48gb"


def test_aliases_and_hostnames_resolve_to_the_listed_name():
    assert hardware.canonical("desktop-d2j5pm9") == "Whitehall"
    assert hardware.canonical("ironwood.local") == "Ironwood"
    assert hardware.canonical("Elsewhere.lan") == "Elsewhere"   # unlisted: the reported short name
    assert hardware.specs("Elsewhere") is None


def test_no_devices_file_lists_nothing(tmp_path, monkeypatch):
    """A fresh clone: nothing listed, and a run on this machine still records its own hardware."""
    monkeypatch.setenv("CRUCIBLE_DEVICES_FILE", str(tmp_path / "missing.yaml"))
    assert hardware.devices() == {} and hardware.specs("Whitehall") is None
    here = {"hostname": "laptop", "cpu": "Apple M3", "gpu": None, "ram_gb": 16.0}
    assert hardware.serving(here, {"same_machine": True}) == here
    assert hardware.serving(here, {"same_machine": False, "device": "Whitehall"}) == {
        "hostname": "Whitehall", "cpu": None, "gpu": None, "ram_gb": None}


def test_malformed_file_reads_as_empty(tmp_path, monkeypatch, capsys):
    path = tmp_path / "devices.yaml"
    path.write_text("devices: [not, a, mapping]\n")
    monkeypatch.setenv("CRUCIBLE_DEVICES_FILE", str(path))
    assert hardware.devices() == {}
    assert "ignoring" in capsys.readouterr().err


def test_add_device_writes_and_rereads(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "devices.yaml"
    monkeypatch.setenv("CRUCIBLE_DEVICES_FILE", str(path))
    hardware.add_device("Bigbox", "AMD Ryzen 9", "NVIDIA GeForce RTX 3090, 24576 MiB", 64, ["bigbox-lan"], ["lmlink:abc"])
    assert hardware.specs("bigbox-lan") == {"hostname": "Bigbox", "cpu": "AMD Ryzen 9",
                                            "gpu": "NVIDIA GeForce RTX 3090, 24576 MiB", "ram_gb": 64.0}
    # Found by ID whatever LM Link calls it now
    assert hardware.resolve("renamed-in-lm-link", ["lmlink:abc"]) == "Bigbox"
    # Updating keeps specs when none are given, and adds IDs instead of replacing them
    hardware.add_device("Bigbox", ids=["machine:m_1"], keep_specs=True)
    assert hardware.devices()["Bigbox"]["ids"] == ["lmlink:abc", "machine:m_1"]
    assert hardware.devices()["Bigbox"]["cpu"] == "AMD Ryzen 9"
    hardware.add_device("Mini", "Apple M4", None, 16)
    assert set(hardware.devices()) == {"Bigbox", "Mini"}
    assert path.read_text().startswith("# The machines")


def test_a_device_found_by_name_has_its_id_remembered():
    assert hardware.resolve("DESKTOP-D2J5PM9", ["lmlink:far"]) == "Whitehall"     # by alias
    hardware.remember("Whitehall", ["lmlink:far"], "DESKTOP-D2J5PM9")
    assert hardware.devices()["Whitehall"]["ids"] == ["lmlink:far"]
    assert hardware.resolve("anything", ["lmlink:far"]) == "Whitehall"            # now by ID


def test_a_peer_listed_without_hardware_has_no_specs(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUCIBLE_DEVICES_FILE", str(tmp_path / "d.yaml"))
    hardware.add_device("Peer", ids=["lmlink:p"], keep_specs=True)
    assert hardware.resolve(None, ["lmlink:p"]) == "Peer" and hardware.specs("Peer") is None
    assert hardware.unlisted({"same_machine": False, "served_via": "LM Link", "device": "Peer",
                              "device_id": "lmlink:p"}) == "Peer"


def test_unlisted_names_only_an_unknown_link_peer():
    assert hardware.unlisted({"same_machine": False, "served_via": "LM Link", "device": "Elsewhere"}) == "Elsewhere"
    assert hardware.unlisted({"same_machine": False, "served_via": "LM Link", "device": "Whitehall"}) is None
    assert hardware.unlisted({"same_machine": True, "device": "Elsewhere"}) is None
    assert hardware.unlisted({"same_machine": False, "served_via": "LM Link", "device": None}) is None


def test_this_machine_is_stamped_with_its_name():
    here = {"hostname": "mbp-2024", "name": "Duskfall", "cpu": "Apple M5 Pro", "gpu": None, "ram_gb": 48.0}
    assert hardware.serving(here, {"same_machine": True})["hostname"] == "Duskfall"
    assert hardware.serving({**here, "name": None}, {"same_machine": True})["hostname"] == "mbp-2024"


def test_describe_reads_like_the_machine():
    assert hardware.describe({"cpu": "Apple M5 Pro", "gpu": None, "ram_gb": 48.0}) == \
        "Apple M5 Pro, 48 GB unified memory (m5-pro-48gb)"
    assert hardware.describe({"cpu": "AMD Ryzen 7 7700", "gpu": "NVIDIA GeForce RTX 5070 Ti, 16303 MiB",
                              "ram_gb": 32.0}) == \
        "AMD Ryzen 7 7700, NVIDIA GeForce RTX 5070 Ti 16GB, 32 GB RAM (rtx-5070-ti-16gb)"
    assert hardware.describe(None) == "unknown hardware"
