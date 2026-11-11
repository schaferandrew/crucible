import pytest

from crucible import hostnames, runrecord
from crucible.hostnames import contains_ip, ip_strings, public_label


@pytest.mark.parametrize("name", ["Ironwood", "duskfall", "Mac-168", "MacBook-Pro-2.local", "m5-pro-48gb",
                                  "node-1-2-3", "whitehall", "Andrews-Mac-mini"])
def test_ordinary_names_pass(name):
    assert public_label(name) == name


@pytest.mark.parametrize("name", ["192.168.1.162", "10.0.0.1", "ip-192-168-1-162", "ip-192-168-1-162.local", "IP-10-0-0-1",
                                  "192-168-1-162", "192-168-1-162.local", "ec2-1-2-3-4.compute.amazonaws.com",
                                  "fe80::1", "::1", "2001:db8::8a2e:370:7334", "[2001:db8::1]", "ip-10", "10.0.1",
                                  "", "   ", None])
def test_addresses_and_ip_derived_names_are_dropped(name):
    assert public_label(name) is None


def test_public_label_trims():
    assert public_label("  Ironwood ") == "Ironwood"


def test_contains_ip_finds_addresses_inside_text_and_ignores_lookalikes():
    assert contains_ip("http://192.168.1.5:1234/v1") and contains_ip("served by ip-172-16-0-9") and contains_ip("peer fe80::1%en0")
    assert not contains_ip("2026-01-01T00:00:00+00:00") and not contains_ip("Q4_K_M") and not contains_ip("1.14.28")
    assert not contains_ip("qwen2.5-0.5b-instruct") and not contains_ip("999.1.1.1") and not contains_ip("sha256:" + "ab" * 32) and not contains_ip("12:30:45")


def test_ip_strings_names_the_path():
    record = {"a": {"label": "ip-192-168-1-162", "ok": "Ironwood"}, "b": ["x", "10.1.2.3"]}
    assert [line.split(":")[0] for line in ip_strings(record)] == ["$.a.label", "$.b[1]"]


def test_records_never_carry_an_ip_host():
    assert runrecord.endpoint_record("lmstudio/x", {"provider": "lmstudio", "device": "ip-192-168-1-162"})["device"] is None
    assert runrecord.endpoint_record("lmstudio/x", {"provider": "lmstudio", "device": "Whitehall"})["device"] == "Whitehall"
    machine = {"hostname": "192.168.1.9", "cpu": "Apple M1 Pro", "gpu": None, "ram_gb": 32.0}
    record = runrecord.hardware_record("lmstudio/x", machine, {"local": True, "same_machine": True})
    assert record["label"] is None and record["key"] == "m1-pro-32gb"
    assert hostnames.public_label("Ironwood") == "Ironwood"
