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
    assert hardware.key(whitehall["cpu"], whitehall["gpu"], whitehall["ram_gb"]) == "rtx-5070-ti-16gb"
    assert hardware.key(ironwood["cpu"], ironwood["gpu"], ironwood["ram_gb"]) == "m1-pro-32gb"
