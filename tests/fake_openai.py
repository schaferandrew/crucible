"""Scripted OpenAI-compatible chat server for agent integration tests.

Speaks just enough of /v1/chat/completions (streaming and not) for an agent
to run a deterministic three-step task without a real model:

  1. call the first MCP mock tool offered (get_weather), else `bash`
  2. call `write` to create answer.txt
  3. reply with a final message
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FINAL_TEXT = "All done: wrote answer.txt. 3 passed"


def _next_step(body: dict) -> dict:
    """Pick the scripted reply from how many tool results the agent sent back."""
    messages = body.get("messages", [])
    tool_names = {t.get("function", {}).get("name") for t in body.get("tools") or []}
    done = sum(1 for m in messages if m.get("role") == "tool")
    if done == 0:
        if "get_weather" in tool_names:
            return {"tool": "get_weather", "args": {}}
        return {"tool": "bash", "args": {"command": "echo hello"}}
    if done == 1:
        return {"tool": "write", "args": {"path": "answer.txt", "content": "done\n"}}
    return {"text": FINAL_TEXT}


class _Handler(BaseHTTPRequestHandler):
    server_version = "fake-openai/1.0"

    def log_message(self, *args):  # keep test output quiet
        pass

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list", "data": [{"id": "fake-model", "object": "model"}]})
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.requests.append(body)
        step = _next_step(body)
        usage = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
        if step.get("tool"):
            delta = {"role": "assistant", "content": None, "tool_calls": [{
                "index": 0, "id": f"call_{len(self.server.requests)}", "type": "function",
                "function": {"name": step["tool"], "arguments": json.dumps(step["args"])},
            }]}
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": step["text"]}
            finish = "stop"

        if not body.get("stream"):
            message = {k: v for k, v in delta.items() if k != "tool_calls"}
            if "tool_calls" in delta:
                message["tool_calls"] = [{k: v for k, v in tc.items() if k != "index"}
                                         for tc in delta["tool_calls"]]
            self._json({"id": "chatcmpl-fake", "object": "chat.completion", "model": body.get("model"),
                        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                        "usage": usage})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        base = {"id": "chatcmpl-fake", "object": "chat.completion.chunk", "model": body.get("model")}
        for chunk in (
            {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
            {**base, "choices": [], "usage": usage},
        ):
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _json(self, payload: dict):
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start() -> ThreadingHTTPServer:
    """Start the server on a free localhost port; caller must .shutdown() it."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    srv = start()
    print(f"http://127.0.0.1:{srv.server_address[1]}/v1", flush=True)
    threading.Event().wait()
