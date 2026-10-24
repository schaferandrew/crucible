#!/usr/bin/env python3
"""crucible's web MCP server (stdio JSON-RPC): web_search and web_fetch.

Declared per prompt with `mcp_servers: [web]`, so every agent gets the same
web tools for tasks like E6 instead of whatever its harness ships. Stdlib
only, since it runs on crucible's own interpreter.

web_search uses the Brave Search API and is only offered when
BRAVE_SEARCH_API_KEY is set; web_fetch needs no key.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "crucible-benchmark/1.0 (+https://github.com/schaferandrew/crucible)"
TIMEOUT_S = 30
DEFAULT_MAX_CHARS = 20000

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web. Returns titles, URLs and snippets of the top results.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Results to return (default 5, max 10)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": ("Fetch a URL with HTTP GET. Returns the status, content type and body "
                        "(HTML reduced to text, JSON and plain text as-is), truncated to max_chars."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "http(s) URL to fetch"},
                "max_chars": {"type": "integer",
                              "description": f"Truncate the body to this many characters (default {DEFAULT_MAX_CHARS})"},
            },
            "required": ["url"],
        },
    },
]


class ToolError(Exception):
    """Reported to the model as an isError tool result, not a protocol error."""


def _get(url: str, headers: dict | None = None) -> tuple[int, str, str]:
    """(status, content type, decoded body) for a GET; HTTP errors included."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            status, ctype, raw = resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as exc:
        status, ctype, raw = exc.code, exc.headers.get("Content-Type", ""), exc.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ToolError(f"Request failed: {exc}") from exc
    charset = re.search(r"charset=([\w-]+)", ctype)
    return status, ctype, raw.decode(charset.group(1) if charset else "utf-8", errors="replace")


def html_to_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", page)
    page = re.sub(r"(?i)<(br|/p|/div|/li|/tr|/h[1-6])\b[^>]*>", "\n", page)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t\r\f\v]+", " ", text)).strip()


def web_fetch(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ToolError("Only http(s) URLs are supported")
    status, ctype, body = _get(url)
    if "html" in ctype:
        body = html_to_text(body)
    if len(body) > max_chars:
        body = body[:max_chars] + f"\n... [truncated at {max_chars} characters]"
    return f"HTTP {status} ({ctype or 'unknown type'})\n\n{body}"


def _brave_search(query: str, max_results: int, api_key: str) -> list[dict]:
    url = ("https://api.search.brave.com/res/v1/web/search?"
           + urllib.parse.urlencode({"q": query, "count": max_results}))
    status, _, body = _get(url, {"Accept": "application/json", "X-Subscription-Token": api_key})
    if status != 200:
        raise ToolError(f"Brave search returned HTTP {status}: {body[:200]}")
    results = json.loads(body).get("web", {}).get("results", [])
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": html_to_text(r.get("description", ""))} for r in results]


def web_search(query: str, max_results: int = 5) -> str:
    max_results = max(1, min(int(max_results), 10))
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        raise ToolError("web_search is unavailable: BRAVE_SEARCH_API_KEY is not set")
    results = _brave_search(query, max_results, api_key)
    if not results:
        return f"No results for: {query}"
    return "\n\n".join(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}"
                       for i, r in enumerate(results, 1))


def available_tools() -> list[dict]:
    """web_search only with a search API key, so models never see a dead tool."""
    return [t for t in TOOLS
            if t["name"] != "web_search" or os.environ.get("BRAVE_SEARCH_API_KEY")]


HANDLERS = {"web_search": web_search, "web_fetch": web_fetch}


def handle(request: dict) -> dict | None:
    """JSON-RPC response for one request (None for notifications)."""
    request_id, method = request.get("id"), request.get("method")
    if request_id is None:
        return None
    params = request.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "crucible-web", "version": "1.0.0"}}
    elif method == "tools/list":
        result = {"tools": available_tools()}
    elif method == "tools/call":
        handler = HANDLERS.get(params.get("name"))
        if handler is None:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {params.get('name')}"}}
        try:
            result = {"content": [{"type": "text", "text": handler(**(params.get("arguments") or {}))}]}
        except (ToolError, TypeError, ValueError) as exc:
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            response = handle(json.loads(line))
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "error": {"code": -32700, "message": f"Invalid JSON: {exc}"}}
        if response:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
