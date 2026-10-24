"""End-to-end: `crucible run` drives the real pi CLI against a scripted model.

Skipped when pi is not installed. Exercises the whole pipeline: workspace
setup, the per-run extension (local provider + mock MCP bridge), the session
dir capture, transcript, and meta.json metrics.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests import fake_openai

pytestmark = pytest.mark.skipif(shutil.which("pi") is None, reason="pi not installed")

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fake_model():
    server = fake_openai.start()
    yield server
    server.shutdown()


def _run_crucible(tmp_path, server, *args):
    port = server.server_address[1]
    env = {
        **os.environ,
        "OLLAMA_BASE_URL": f"http://127.0.0.1:{port}",
        "PI_OFFLINE": "1",
        # never route the local fake through an HTTP(S) proxy
        "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        "PI_CODING_AGENT_DIR": str(tmp_path / "pi-home"),  # isolate from ~/.pi
    }
    return subprocess.run(
        [sys.executable, "-m", "crucible.cli", "run", *args, "--agent", "pi",
         "--model", "ollama/fake-model", "--timeout", "120", "--output", str(tmp_path / "runs")],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL, timeout=180,
    )


def test_e4_with_mock_mcp(tmp_path, fake_model):
    proc = _run_crucible(tmp_path, fake_model, "E4")
    assert proc.returncode == 0, proc.stdout + proc.stderr

    (run_dir,) = (tmp_path / "runs" / "ollama_fake-model" / "everyday" / "E4").iterdir()
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["agent"] == "pi"
    assert meta["returncode"] == 0 and not meta["timed_out"]
    assert meta["metrics"]["tool_calls"] == 2
    assert meta["metrics"]["tokens_in"] == 300 and meta["metrics"]["tokens_out"] == 30
    assert meta["metrics"]["tests_passed"] == 3

    events = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
    calls = [e["name"] for e in events if e["type"] == "toolCall"]
    assert calls == ["get_weather", "write"]
    weather = next(e for e in events if e["type"] == "toolCallResult")
    assert "Saint Paul" in weather["result"]  # served by the mock MCP server

    assert (run_dir / "workspace" / "answer.txt").read_text(encoding="utf-8") == "done\n"
    assert fake_openai.FINAL_TEXT in (run_dir / "stdout.txt").read_text(encoding="utf-8")

    # The prompt reached the model as an attached file, rubric excluded
    first_user = fake_model.requests[0]["messages"][-1]["content"]
    first_user = first_user if isinstance(first_user, str) else json.dumps(first_user)
    assert "morning brief" in first_user
    assert "Proper Language Switching" not in first_user
