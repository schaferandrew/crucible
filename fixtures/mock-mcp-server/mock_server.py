#!/usr/bin/env python3
"""Python MCP server for mock data - handles stdio JSON-RPC protocol.

Provides tools: get_emails, get_calendar_events, get_news, get_weather
with realistic tool definitions backed by fixture data files.
"""
import json
import sys
from pathlib import Path


class MCPServer:
    """A minimal MCP-compliant server over stdio JSON-RPC.

    Responds to initialize, tools/list, and tools/call requests by reading
    fixture data from fixtures/mock-data/<tool_name>.json.
    """

    def __init__(self):
        # mock_data lives one level up from mock-mcp-server/
        self.fixtures_dir = Path(__file__).resolve().parent.parent / "mock-data"
        self._tool_data = {
            "get_emails": "emails.json",
            "get_calendar_events": "calendar.json",
            "get_news": "news.json",
            "get_weather": "weather.json",
        }

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    def send_response(self, result, request_id=None):
        """Send a JSON-RPC 2.0 success response."""
        response: dict = {"jsonrpc": "2.0", "result": result}
        if request_id is not None:
            response["id"] = request_id
        print(json.dumps(response), flush=True)

    def send_error(self, code, message, request_id=None):
        """Send a JSON-RPC 2.0 error response."""
        response: dict = {"jsonrpc": "2.0", "error": {"code": code, "message": message}}
        if request_id is not None:
            response["id"] = request_id
        print(json.dumps(response), flush=True)

    # ------------------------------------------------------------------
    # MCP protocol handlers
    # ------------------------------------------------------------------

    def handle_initialize(self, params, request_id):
        """Respond to initialize with protocol version and tool capability."""
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mock-data-server", "version": "1.0.0"},
        }
        self.send_response(result, request_id)

    def handle_tools_list(self, params, request_id):
        """List available tools with real-world tool definitions."""
        result = {
            "tools": [
                {
                    "name": "get_emails",
                    "description": "Get emails from yesterday for the user's account",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                {
                    "name": "get_calendar_events",
                    "description": "Get upcoming calendar events for the user",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                {
                    "name": "get_news",
                    "description": "Get news for the user's location",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                {
                    "name": "get_weather",
                    "description": "Get weather forecast for the user's location",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            ]
        }
        self.send_response(result, request_id)

    def handle_tools_call(self, params, request_id):
        """Call a tool and return fixture data wrapped in MCP text content."""
        tool_name = params.get("name", "")

        fixture_file = self._tool_data.get(tool_name)
        if fixture_file is None:
            self.send_error(-32601, f"Unknown tool: {tool_name}", request_id)
            return

        fixture_path = self.fixtures_dir / fixture_file
        if not fixture_path.exists():
            self.send_error(-32000, f"Fixture not found: {fixture_path}", request_id)
            return

        try:
            with open(fixture_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            self.send_error(-32000, f"Error loading fixture: {exc}", request_id)
            return

        result = {"content": [{"type": "text", "text": json.dumps(data)}]}
        self.send_response(result, request_id)

    # ------------------------------------------------------------------
    # Dispatch & run loop
    # ------------------------------------------------------------------

    def handle_request(self, line):
        """Parse and dispatch a single JSON-RPC request line."""
        try:
            request = json.loads(line.strip())
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})

            if method == "initialize":
                self.handle_initialize(params, request_id)
            elif method == "tools/list":
                self.handle_tools_list(params, request_id)
            elif method == "tools/call":
                self.handle_tools_call(params, request_id)
            else:
                self.send_error(-32601, f"Unknown method: {method}", request_id)
        except json.JSONDecodeError as exc:
            self.send_error(-32700, f"Invalid JSON: {exc}")
        except Exception as exc:  # noqa: BLE001 — never crash the server loop
            self.send_error(-32000, f"Internal error: {exc}")

    def run(self):
        """Main run loop — reads one JSON-RPC request per line from stdin."""
        for line in sys.stdin:
            if line.strip():
                self.handle_request(line)


if __name__ == "__main__":
    server = MCPServer()
    server.run()
