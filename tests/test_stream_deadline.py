"""A response that never stops streaming is cut off at the run timeout, keeping what arrived."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from crucible import providers


class _EndlessHandler(BaseHTTPRequestHandler):
    """Streams a token every 50ms forever, like a model stuck in a loop."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.end_headers()
        ollama = self.path.endswith("/api/generate")
        try:
            while True:
                if ollama:
                    line = json.dumps({"response": "loop ", "done": False}) + "\n"
                else:
                    line = "data: " + json.dumps({"choices": [{"delta": {"content": "loop "}}]}) + "\n\n"
                self.wfile.write(line.encode())
                self.wfile.flush()
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture
def endless():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EndlessHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_openai_compatible_stream_stops_at_deadline(endless):
    start = time.monotonic()
    with pytest.raises(providers.StreamTimeout) as exc:
        providers._call_openai_compatible(f"{endless}/v1", "m", "p", timeout=1)
    assert time.monotonic() - start < 5
    assert exc.value.partial["text"].startswith("loop ")
    assert exc.value.partial["ttft_s"] is not None


def test_ollama_stream_stops_at_deadline(endless, monkeypatch):
    monkeypatch.setattr(providers, "OLLAMA_BASE_URL", endless)
    with pytest.raises(providers.StreamTimeout) as exc:
        providers._call_ollama("m", "p", timeout=1)
    assert exc.value.partial["text"].startswith("loop ")
