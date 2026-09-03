# MCP Mocking Strategy for Email, Calendar, News, Weather Data

## Overview

Mocking MCP servers to provide fake data for email, calendar, news, and weather tools in the Crucible benchmark suite. Required for tests like E4 that need external data sources.

## Recommended Approach: Python MCP Server

A Python-based MCP server is recommended because:
- No new dependencies - uses stdlib only
- Integrates with existing Python test infrastructure
- Simpler for headless testing
- Direct control over fixture data injection

## Implementation

### MCP Server Implementation

**`fixtures/mock-mcp-server/mock_server.py`:**

```python
#!/usr/bin/env python3
"""Python MCP server for mock data - handles stdio JSON-RPC protocol."""
import json
import sys
from pathlib import Path

class MCPServer:
    def __init__(self):
        self.fixtures_dir = Path(__file__).parent.parent / "mock-data"
    
    def send_response(self, result, request_id=None):
        response = {"result": result}
        if request_id is not None:
            response["id"] = request_id
        print(json.dumps(response), flush=True)
    
    def send_error(self, code, message, request_id=None):
        response = {
            "error": {"code": code, "message": message}
        }
        if request_id is not None:
            response["id"] = request_id
        print(json.dumps(response), flush=True)
    
    def handle_initialize(self, params, request_id):
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mock-data-server", "version": "1.0.0"}
        }
        self.send_response(result, request_id)
    
    def handle_tools_list(self, params, request_id):
        result = {
            "tools": [
                {
                    "name": "get_emails",
                    "description": "Get emails from yesterday for the user's account",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "get_calendar_events",
                    "description": "Get upcoming calendar events for the user",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "get_news",
                    "description": "Get news for the user's location",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "get_weather",
                    "description": "Get weather forecast for the user's location",
                    "inputSchema": {"type": "object", "properties": {}}
                }
            ]
        }
        self.send_response(result, request_id)
    
    def handle_tools_call(self, params, request_id):
        tool_name = params.get("name", "")
        
        if tool_name == "get_emails":
            with open(self.fixtures_dir / "emails.json") as f:
                data = json.load(f)
        elif tool_name == "get_calendar_events":
            with open(self.fixtures_dir / "calendar.json") as f:
                data = json.load(f)
        elif tool_name == "get_news":
            with open(self.fixtures_dir / "news.json") as f:
                data = json.load(f)
        elif tool_name == "get_weather":
            with open(self.fixtures_dir / "weather.json") as f:
                data = json.load(f)
        else:
            self.send_error(-1, f"Unknown tool: {tool_name}", request_id)
            return
        
        result = {"content": [{"type": "text", "text": json.dumps(data)}]}
        self.send_response(result, request_id)
    
    def handle_request(self, line):
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
                self.send_error(-1, f"Unknown method: {method}", request_id)
        except json.JSONDecodeError as e:
            self.send_error(-1, f"Invalid JSON: {e}")
    
    def run(self):
        """Main run loop - reads from stdin, writes to stdout."""
        for line in sys.stdin:
            if line.strip():
                self.handle_request(line)

if __name__ == "__main__":
    server = MCPServer()
    server.run()
```

### MCP Protocol Flow

1. Client sends `initialize` request
2. Server responds with capabilities
3. Client calls `tools/list` to discover tools
4. Client calls `tools/call` with tool name and arguments
5. Server returns fixture data

### Mock Data Files

Create `fixtures/mock-data/` directory with:

**`fixtures/mock-data/emails.json`:**
```json
{
  "yesterday": [
    {
      "from": "alex@example.com",
      "subject": "Project update - Q3 review completed",
      "body": "The Q3 review is now complete and ahead of schedule. Let's discuss the results in our planning meeting.",
      "timestamp": "2026-09-01T10:30:00Z"
    },
    {
      "from": "jamie@example.com",
      "subject": "Meeting notes from yesterday",
      "body": "Notes from yesterday's 1-on-1: discussed career goals, next quarter priorities, and team building activities.",
      "timestamp": "2026-09-01T09:00:00Z"
    }
  ]
}
```

**`fixtures/mock-data/calendar.json`:**
```json
{
  "timezone": "America/Chicago",
  "window": {"start": "2026-09-01T00:00:00Z", "end": "2026-09-08T00:00:00Z"},
  "events": [
    {"start": "2026-09-01T10:00:00Z", "end": "2026-09-01T11:00:00Z", "title": "Team standup", "location": "Zoom"},
    {"start": "2026-09-02T14:00:00Z", "end": "2026-09-02T15:00:00Z", "title": "Project review", "location": "Conference Room A"}
  ]
}
```

**`fixtures/mock-data/news.json`:**
```json
{
  "location": "Saint Paul, MN",
  "articles": [
    {
      "title": "Twin Cities Tech Conference Returns",
      "summary": "Annual tech conference returns to Minneapolis with 50+ speakers",
      "source": "StarTribune",
      "importance": "high"
    },
    {
      "title": "Maplewood Park Renovation Complete",
      "summary": "Renovations to Maplewood Park finished ahead of schedule",
      "source": "Pioneer Press",
      "importance": "medium"
    }
  ]
}
```

**`fixtures/mock-data/weather.json`:**
```json
{
  "location": "Saint Paul, MN",
  "forecast": [
    {
      "date": "2026-09-01",
      "high": 72,
      "low": 58,
      "condition": "Sunny",
      "precipitation": 0
    },
    {
      "date": "2026-09-02",
      "high": 68,
      "low": 55,
      "condition": "Partly Cloudy",
      "precipitation": 10
    }
  ]
}
```

### Configure Opencode

Create or update opencode MCP configuration at `~/.config/opencode/servers.json`:

```json
{
  "servers": {
    "mock-data": {
      "command": "python3",
      "args": ["/path/to/crucible/fixtures/mock-mcp-server/mock_server.py"],
      "env": {}
    }
  }
}
```

### Quick Start Commands

```bash
# 1. Create required directories
mkdir -p fixtures/mock-mcp-server fixtures/mock-data

# 2. Create mock data files (emails.json, calendar.json, news.json, weather.json)

# 3. Create mock MCP server (fixtures/mock-mcp-server/mock_server.py)

# 4. Make executable
chmod +x fixtures/mock-mcp-server/mock_server.py

# 5. Configure opencode MCP server settings
# Add to ~/.config/opencode/servers.json

# 6. Validate mock server works
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | python3 fixtures/mock-mcp-server/mock_server.py

# 7. Run E4 test with mock server active
crucible run E4 --agent pool
```

### Integration with Existing Infrastructure

The mock MCP server integrates with:
- **Opencode**: Via configuration files or environment setup
- **Pool agent**: Via subprocess spawning
- **Crucible test runner**: Extends existing fixture pattern to MCP tools

### Testing Strategy

1. Verify mock server starts and responds to `initialize` and `tools/list`
2. Test each tool (get_emails, get_calendar_events, get_news, get_weather) returns valid fixture data
3. Run E4 test with mock server active via opencode or pool agent
4. Verify Spanish paragraph is generated correctly at end of briefing
5. Verify all fixture files are properly integrated

## Files to Create

1. `fixtures/mock-mcp-server/mock_server.py` - Python MCP server
2. `fixtures/mock-data/emails.json` - Email fixture data
3. `fixtures/mock-data/calendar.json` - Calendar fixture data
4. `fixtures/mock-data/news.json` - News fixture data
5. `fixtures/mock-data/weather.json` - Weather fixture data