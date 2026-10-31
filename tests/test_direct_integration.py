"""--agent direct streams the provider API: text, tokens and TTFT recorded."""
import json
import os
import subprocess
import sys
import uuid
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
        [sys.executable, "-m", "crucible.cli", "run", "seating-logic-puzzle", "--agent", "direct",
         "--model", f"{provider}/fake-model", "--output", str(tmp_path / "runs")],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (run_dir,) = (tmp_path / "runs").glob(f"{provider}_fake-model/seating-logic-puzzle/*")
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert (run_dir / "stdout.txt").read_text(encoding="utf-8") == fake_openai.FINAL_TEXT
    assert (meta["metrics"]["tokens_in"], meta["metrics"]["tokens_out"]) == (100, 10)
    assert fake_openai.FIRST_TOKEN_DELAY_S <= meta["metrics"]["ttft_s"] < 5
    assert meta["metrics"]["model_responses"] == 1
    assert "TTFT" in proc.stdout
    # The 3.0.0 run record
    assert meta["record"] == "run" and meta["format_version"] == 3
    assert uuid.UUID(meta["run_uuid"]).version == 4
    assert meta["run_path"] == f"{provider}_fake-model/seating-logic-puzzle/{run_dir.name}"
    assert meta["task"]["id"] == "seating-logic-puzzle" and meta["task"]["content_hash"]
    assert meta["provenance"]["machine_id"].startswith("m_") and meta["provenance"]["source"] == "crucible-run"
    assert meta["model"]["base"] == "fake-model" and meta["model"]["reasoning"]["requested"] == "default"
    # No prefix, no file on this machine, no metadata from the fake server: an origin that found nothing
    assert meta["model"]["origin"] == {"maker": None, "base_repo": None, "params": None, "active_params": None,
                                       "source": "none"}
    assert meta["endpoint"]["where"] == "local" and meta["endpoint"]["upstream"] is None
    assert meta["hardware"]["key"]  # a local run on this machine
    assert meta["outcome"]["status"] == "completed"
    from crucible import bundle
    assert bundle.record_problems("run", bundle.published_run(meta, "x")) == []


def test_eval_run_is_graded_automatically(tmp_path, fake_model):
    """Evals score themselves after the run; a reply without a GRADE line earns 0 and is flagged."""
    base = f"http://127.0.0.1:{fake_model.server_address[1]}"
    env = {**os.environ, "OLLAMA_BASE_URL": base,
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    proc = subprocess.run(
        [sys.executable, "-m", "crucible.cli", "run", "EVAL-3", "--agent", "direct",
         "--model", "ollama/fake-model", "--output", str(tmp_path / "runs")],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "EVAL-3 is now grade-binary-search-answer" in proc.stdout  # an old ID still works, with a notice
    (run_dir,) = (tmp_path / "runs").glob("ollama_fake-model/grade-binary-search-answer/*")
    (path,) = (run_dir / "scores").glob("*.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == f"r{record['rubric_version']}.checks.json" and record["method"] == "checks"
    assert record["score"] == 0 and record["raw"]["passed"] == 0 and record["raw"]["unit"] == "points"
    assert record["groups"][0]["passed"] == 0 and "no valid GRADE line" in record["groups"][0]["detail"]
    assert record["checked_text"] == fake_openai.FINAL_TEXT  # the grader's reasoning is kept
    from crucible import bundle
    assert bundle.record_problems("score", record) == []
