"""End-to-end with the REAL pool CLI in standalone mode against a scripted model.

Opt-in (CRUCIBLE_REAL_POOL=1) because it edits pool's real settings.yaml for
the run; CI's `pool` job sets it. No Poolside login is needed: ollama-style
standalone mode points pool at tests/fake_openai.py.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests import fake_openai

pytestmark = pytest.mark.skipif(
    not os.environ.get("CRUCIBLE_REAL_POOL") or shutil.which("pool") is None,
    reason="set CRUCIBLE_REAL_POOL=1 with pool installed")

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fake_model():
    server = fake_openai.start()
    yield server
    server.shutdown()


def test_e4_headless_real_pool(tmp_path, fake_model):
    env = {**os.environ,
           "OLLAMA_BASE_URL": f"http://127.0.0.1:{fake_model.server_address[1]}",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    out_dir = Path(os.environ.get("CRUCIBLE_TEST_RUNS", tmp_path / "runs"))
    proc = subprocess.run(
        [sys.executable, "-m", "crucible.cli", "run", "E4", "--agent", "pool",
         "--model", "ollama/fake-model", "--timeout", "180", "--output", str(out_dir)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL, timeout=300,
    )
    print(proc.stdout, proc.stderr)
    (run_dir,) = (out_dir / "ollama_fake-model" / "everyday" / "E4").iterdir()
    for name in ("command.sh", "stdout.txt", "stderr.txt", "meta.json"):
        print(f"----- {name}\n{(run_dir / name).read_text(encoding='utf-8', errors='replace')[:4000]}")
    print(f"----- requests seen by fake model: {len(fake_model.requests)}")
    for body in fake_model.requests[:1]:
        print("tools offered:", [t.get("function", {}).get("name") for t in body.get("tools") or []])

    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["returncode"] == 0, "pool exec failed; see output above"
    assert fake_model.requests, "pool never called the standalone model"
    transcript = (run_dir / "stdout.txt").read_text(encoding="utf-8")
    assert fake_openai.FINAL_TEXT in transcript
    # The mock MCP server was provisioned for the run and pool offered its tools
    offered = {t.get("function", {}).get("name") for t in fake_model.requests[0].get("tools") or []}
    assert any(n and n.endswith("get_weather") for n in offered)
