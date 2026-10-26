"""--agent direct streams the provider API: text, tokens and TTFT recorded."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import fake_openai

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fake_model():
    server = fake_openai.start()
    yield server
    server.shutdown()


@pytest.mark.parametrize("provider", ["ollama", "lmstudio"])
def test_direct_records_tokens_and_ttft(tmp_path, fake_model, provider):
    base = f"http://127.0.0.1:{fake_model.server_address[1]}"
    env = {**os.environ, "OLLAMA_BASE_URL": base, "LMSTUDIO_BASE_URL": f"{base}/v1",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    proc = subprocess.run(
        [sys.executable, "-m", "crucible.cli", "run", "G1", "--agent", "direct",
         "--model", f"{provider}/fake-model", "--output", str(tmp_path / "runs")],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (run_dir,) = (tmp_path / "runs").glob(f"{provider}_fake-model/*/G1/*")
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert (run_dir / "stdout.txt").read_text(encoding="utf-8") == fake_openai.FINAL_TEXT
    assert (meta["metrics"]["tokens_in"], meta["metrics"]["tokens_out"]) == (100, 10)
    assert fake_openai.FIRST_TOKEN_DELAY_S <= meta["metrics"]["ttft_s"] < 5
    assert meta["metrics"]["model_responses"] == 1
    assert "TTFT" in proc.stdout


def test_eval_run_is_graded_automatically(tmp_path, fake_model):
    """Evals score themselves after the run; a reply without a GRADE line earns 0 and is flagged."""
    base = f"http://127.0.0.1:{fake_model.server_address[1]}"
    env = {**os.environ, "OLLAMA_BASE_URL": base,
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    proc = subprocess.run(
        [sys.executable, "-m", "crucible.cli", "run", "V3", "--agent", "direct",
         "--model", "ollama/fake-model", "--output", str(tmp_path / "runs")],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (run_dir,) = (tmp_path / "runs").glob("ollama_fake-model/evals/V3/*")
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    assert results["scores"]["Grade accuracy"] == 0
    assert results["scores"]["_eval"]["parsed"] is False
    assert results["scores"]["_eval"]["reasoning"] == fake_openai.FINAL_TEXT
    assert "No valid `GRADE:` line" in (run_dir / "reasoning.md").read_text(encoding="utf-8")
