"""Which device runs a model, and naming the ones the devices file doesn't know (crucible/hardware.py)."""
import pytest

from crucible import environment, exporter, hardware, provenance

HERE = {"hostname": "mbp", "os": "Darwin", "arch": "arm64", "cpu": "Apple M5 Pro", "gpu": None, "ram_gb": 48.0}
LINK = {"status": "online", "deviceIdentifier": "me", "deviceName": "mbp",
        "peers": [{"deviceIdentifier": "pc", "deviceName": "DESKTOP-XYZ", "status": "connected"},
                  {"deviceIdentifier": "old", "deviceName": "Attic", "status": "disconnected"}]}


@pytest.fixture
def empty(tmp_path, monkeypatch):
    """A fresh install: no devices file, this machine is an M5 Pro, LM Link has one connected peer."""
    monkeypatch.setenv("CRUCIBLE_DEVICES_FILE", str(tmp_path / "devices.yaml"))
    monkeypatch.setattr(environment, "machine", lambda: dict(HERE))
    monkeypatch.setattr(environment, "_link", lambda: LINK)
    return tmp_path / "devices.yaml"


def _serving(monkeypatch, record):
    monkeypatch.setattr(environment, "inference", lambda model, device=True: record)


def _me():
    return hardware.machine_ref(provenance.machine_id())


def test_a_loaded_peer_is_the_only_device_asked_about(empty, monkeypatch):
    _serving(monkeypatch, {"device_id": "lmlink:pc", "same_machine": False, "served_via": "LM Link"})
    (peer,) = environment.known_devices("lmstudio/qwen/qwen3.5-9b")
    assert (peer["this_machine"], peer["reported"], peer["name"]) == (False, "DESKTOP-XYZ", None)
    assert environment.needs_naming(peer)


def test_a_model_on_this_machine_asks_about_this_machine(empty, monkeypatch):
    _serving(monkeypatch, {"device_id": "lmlink:me", "same_machine": True})
    (here,) = environment.known_devices("lmstudio/gemma")
    assert here["this_machine"] and here["specs"]["cpu"] == "Apple M5 Pro"
    assert set(here["ids"]) == {_me(), "lmlink:me"}


def test_an_unloaded_model_uses_the_preferred_device(empty, monkeypatch):
    _serving(monkeypatch, {"expected_variant": {"device_id": "lmlink:pc"}})
    assert [d["reported"] for d in environment.known_devices("lmstudio/x")] == ["DESKTOP-XYZ"]


def test_an_unknown_route_asks_about_every_connected_device(empty, monkeypatch):
    _serving(monkeypatch, {})
    assert [d["reported"] for d in environment.known_devices("lmstudio/x")] == ["mbp", "DESKTOP-XYZ"]
    # setup covers every peer LM Link knows, connected or not
    assert [d["reported"] for d in environment.known_devices()] == ["mbp", "DESKTOP-XYZ", "Attic"]


def test_ollama_on_this_machine_needs_only_this_machine(empty, monkeypatch):
    (here,) = environment.known_devices("ollama/qwen3:8b")
    assert here["this_machine"] and here["ids"] == [_me()]   # no LM Link lookup for Ollama


def test_cloud_and_remote_servers_need_nothing(empty, monkeypatch):
    assert environment.known_devices("openrouter/moonshotai/kimi-k2.6") == []
    monkeypatch.setitem(environment.PROVIDER_BASE_URLS, "ollama", lambda: "http://10.0.0.5:11434")
    assert environment.known_devices("ollama/qwen3:8b") == []


def test_a_device_named_by_hand_is_linked_by_name_then_id(empty, monkeypatch):
    hardware.add_device("Whitehall", "AMD Ryzen 7 7700", "NVIDIA RTX 5070 Ti 16GB", 32, aliases=["desktop-xyz"])
    _serving(monkeypatch, {"device_id": "lmlink:pc"})
    (peer,) = environment.known_devices("lmstudio/x")
    assert peer["name"] == "Whitehall" and not environment.needs_naming(peer)
    assert "lmlink:pc" in hardware.devices()["Whitehall"]["ids"]


def test_naming_this_machine_asks_only_for_a_name(empty, monkeypatch, capsys):
    _serving(monkeypatch, {"device_id": "lmlink:me", "same_machine": True})
    monkeypatch.setattr(hardware, "_interactive", lambda: True)
    answers = iter(["Duskfall"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    hardware.check_devices(environment.known_devices("lmstudio/gemma"), seen=set())
    assert "This model runs on this machine: Apple M5 Pro, 48 GB unified memory (m5-pro-48gb)" in capsys.readouterr().out
    entry = hardware.devices()["Duskfall"]
    assert entry["cpu"] == "Apple M5 Pro" and entry["ram_gb"] == 48.0 and "lmlink:me" in entry["ids"]
    # The run is stamped with it from now on
    found = {"same_machine": True, "device_id": "lmlink:me", "device_reported": "mbp"}
    assert environment.this_machine_name(found, "mbp") == "Duskfall"
    assert environment.this_machine_name({}, "mbp") == "Duskfall"      # by machine ID, e.g. an Ollama run
    # ... and isn't asked about again
    assert not any(environment.needs_naming(d) for d in environment.known_devices("lmstudio/gemma"))


def test_naming_a_peer_asks_for_its_hardware(empty, monkeypatch):
    _serving(monkeypatch, {"device_id": "lmlink:pc"})
    monkeypatch.setattr(hardware, "_interactive", lambda: True)
    answers = iter(["Whitehall", "AMD Ryzen 7 7700", "NVIDIA RTX 5070 Ti 16GB", "32"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    hardware.check_devices(environment.known_devices("lmstudio/x"), seen=set())
    found = hardware.specs(None, ["lmlink:pc"])
    assert found["hostname"] == "Whitehall" and hardware.key(found["cpu"], found["gpu"], found["ram_gb"]) == "rtx-5070-ti-16gb"
    assert hardware.devices()["Whitehall"]["aliases"] == ["DESKTOP-XYZ"]
    run = {"same_machine": False, "served_via": "LM Link", "device_id": "lmlink:pc", "device": "Whitehall"}
    assert hardware.serving(HERE, run)["gpu"] == "NVIDIA RTX 5070 Ti 16GB"


def test_off_a_terminal_it_only_says_what_is_missing(empty, monkeypatch, capsys):
    _serving(monkeypatch, {"device_id": "lmlink:pc"})
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("asked off a terminal"))
    seen = set()
    hardware.check_devices(environment.known_devices("lmstudio/x"), seen=seen)
    hardware.check_devices(environment.known_devices("lmstudio/x"), seen=seen)
    out = capsys.readouterr().out
    assert out.count("crucible devices setup") == 1 and not empty.exists()


def test_skipping_a_question_saves_nothing(empty, monkeypatch):
    _serving(monkeypatch, {"device_id": "lmlink:pc"})
    monkeypatch.setattr(hardware, "_interactive", lambda: True)

    def interrupted(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", interrupted)
    hardware.check_devices(environment.known_devices("lmstudio/x"), seen=set())
    assert hardware.devices() == {}


def test_a_past_run_exports_the_hardware_it_recorded(empty):
    """A fresh install has no devices file, but a run recorded its peer's specs when it was made."""
    recorded = {"key": "rtx-5070-ti-16gb", "class": "discrete_gpu", "cpu": "AMD Ryzen 7 7700",
                "accelerators": [{"name": "NVIDIA RTX 5070 Ti 16GB", "memory_gb": 16, "count": 1}],
                "system_memory_gb": 32.0, "offload": None, "label": "Whitehall"}
    inference = {"local": True, "same_machine": False, "served_via": "LM Link", "device": "Whitehall"}
    out = exporter._hardware(HERE, inference, recorded)
    assert out == {"hostname": "Whitehall", "cpu": "AMD Ryzen 7 7700", "gpu": "NVIDIA RTX 5070 Ti 16GB", "ram_gb": 32.0}
    assert hardware.key(out["cpu"], out["gpu"], out["ram_gb"]) == recorded["key"]
