"""Stand-in for the pool CLI, used by tests/test_pool_integration.py.

`pool exec ... -o json` prints NLJSON events like the real CLI and records
the MCP servers present in settings.yaml while it ran, so the test can check
the harness provisioned them for the run and removed them afterwards.
"""
import json
import sys
from pathlib import Path

import yaml

args = sys.argv[1:]
if args[:1] != ["exec"]:
    sys.exit(2)
workspace = Path(args[args.index("-d") + 1])
settings = Path.home() / ".config" / "poolside" / "settings.yaml"
servers = sorted((yaml.safe_load(settings.read_text(encoding="utf-8")) or {}).get("mcp_servers", {})) \
    if settings.exists() else []
(workspace / "mcp_seen.json").write_text(json.dumps(servers), encoding="utf-8")
for event in (
    {"type": "toolCall", "name": "get_weather", "args": {}},
    {"type": "toolCallResult", "result": "Saint Paul, MN"},
    {"type": "assistantMessage", "message": "Brief done. 2 passed"},
):
    print(json.dumps(event), flush=True)
