"""Helpers for the hidden tests: run the model's CLI from the grading copy's root, like a user would."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the grading copy: interest/, tests/ and README.md as the model left them
CENT = 0.0100001  # "off by more than a cent" fails


def run(*args):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-m", "interest", *map(str, args)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=30)


def flags(principal=1000, rate=5, years=None, months=None, compound="monthly", contribution=None, frequency=None):
    out = ["--principal", principal, "--rate", rate]
    if years is not None:
        out += ["--years", years]
    if months is not None:
        out += ["--months", months]
    out += ["--compound", compound]
    if contribution is not None:
        out += ["--contribution", contribution]
    if frequency is not None:
        out += ["--contribution-frequency", frequency]
    return out


def calc(**kw):
    """The --json result of a valid run, as a dict."""
    result = run(*flags(**kw), "--json")
    assert result.returncode == 0, f"exit {result.returncode}: {result.stderr.strip()[-200:]}"
    return json.loads(result.stdout)


def assert_close(actual, expected, what="final_balance"):
    assert abs(actual - expected) <= CENT, f"{what}: got {actual}, expected {expected}"
