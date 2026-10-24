"""End-to-end `crucible run --agent pool` against a stand-in pool CLI.

The real pool CLI needs Poolside credentials, so tests/fake_pool.py plays its
part. This still exercises the harness wiring: preflight, MCP provisioning in
settings.yaml (and its removal), headless NLJSON capture and meta.json.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _install_fake_pool(bin_dir: Path) -> None:
    bin_dir.mkdir()
    script = REPO_ROOT / "tests" / "fake_pool.py"
    if os.name == "nt":
        (bin_dir / "pool.cmd").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        shim = bin_dir / "pool"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)


def test_e4_headless_provisions_and_cleans_mcp(tmp_path):
    home = tmp_path / "home"
    settings = home / ".config" / "poolside" / "settings.yaml"
    settings.parent.mkdir(parents=True)
    settings.write_text(yaml.safe_dump({"theme": "dark"}), encoding="utf-8")
    _install_fake_pool(tmp_path / "bin")

    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home),
           "PATH": str(tmp_path / "bin") + os.pathsep + os.environ["PATH"]}
    proc = subprocess.run(
        [sys.executable, "-m", "crucible.cli", "run", "E4", "--agent", "pool",
         "--timeout", "60", "--output", str(tmp_path / "runs")],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    # Tenant mode is recorded as model "pool", as before the refactor
    (run_dir,) = (tmp_path / "runs" / "pool" / "everyday" / "E4").iterdir()
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["agent"] == "pool" and meta["model"] == "pool"
    assert meta["returncode"] == 0
    assert meta["metrics"]["tool_calls"] == 1
    assert meta["metrics"]["tests_passed"] == 2

    # mock-data existed in settings.yaml during the run and is gone after;
    # unrelated user settings survive
    assert json.loads((run_dir / "workspace" / "mcp_seen.json").read_text()) == ["mock-data"]
    assert yaml.safe_load(settings.read_text(encoding="utf-8")) == {"theme": "dark"}

    transcript = (run_dir / "stdout.txt").read_text(encoding="utf-8")
    assert "⏺ get_weather()" in transcript and "⏺ Brief done. 2 passed" in transcript
