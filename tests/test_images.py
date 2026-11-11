"""Tasks can attach images: the direct harness sends them as image parts, other harnesses refuse."""
import base64

import pytest

from crucible import providers, versioning, workspace
from crucible.agents import direct
from crucible.agents.base import Agent
from crucible.agents.direct import DirectAgent
from tests import fake_openai

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


@pytest.fixture
def server(monkeypatch):
    s = fake_openai.start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    yield s
    s.shutdown()


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "fan.png"
    path.write_bytes(PNG)
    return path


def test_openai_compatible_sends_image_parts(server, image):
    base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    providers._call_openai_compatible(base, "fake-model", "Who?", 10, images=[image])
    (content,) = [m["content"] for m in server.requests[-1]["messages"]]
    assert content[0] == {"type": "text", "text": "Who?"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(PNG).decode()


def test_openai_compatible_without_images_sends_plain_text(server):
    base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    providers._call_openai_compatible(base, "fake-model", "Who?", 10)
    assert server.requests[-1]["messages"] == [{"role": "user", "content": "Who?"}]


def test_ollama_sends_images(server, image, monkeypatch):
    monkeypatch.setattr(providers, "OLLAMA_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")
    providers._call_ollama("fake-model", "Who?", 10, images=[image])
    assert server.requests[-1]["images"] == [base64.b64encode(PNG).decode()]


def test_only_direct_attaches_images(monkeypatch):
    task = {"needs_tools": False, "images": ["images/x.png"]}
    harness = type("Harness", (Agent,), {"name": "harness"})()
    assert "can't send" in harness.check("lmstudio/m", task)
    assert harness.check("lmstudio/m", {"needs_tools": False}) is None
    monkeypatch.setattr(direct, "missing_images", lambda names: [])
    assert DirectAgent().check("lmstudio/m", task) is None


def test_direct_refuses_a_missing_image():
    task = {"needs_tools": False, "images": ["images/not-there.png"]}
    assert "image not found" in DirectAgent().check("lmstudio/m", task)


def test_image_bytes_are_task_content(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "FIXTURES_DIR", tmp_path)
    task = {"prompt": "Who?", "images": ["fan.png"]}
    (tmp_path / "fan.png").write_bytes(PNG)
    before = versioning.content_hash(task)
    (tmp_path / "fan.png").write_bytes(PNG + b"x")
    assert versioning.content_hash(task) != before
    # A task without images hashes as it always did
    assert versioning.content_hash({"prompt": "Who?"}) == versioning.content_hash({"prompt": "Who?", "images": []})
