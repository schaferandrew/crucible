#!/usr/bin/env python3
"""Dummy travel MCP server (stdio JSON-RPC, stdlib only) for the travel-planning task.

Tools: search_flights, search_restaurants, get_restaurant, get_distance, get_travel_time.
All data is fictional and comes from world.json next to this file.
"""
import json
import sys
from pathlib import Path

WORLD = json.loads((Path(__file__).resolve().parent / "world.json").read_text(encoding="utf-8"))


def _norm(value):
    return "".join(c for c in str(value).lower() if c.isalnum())


def _resolve(ref):
    """An id or a name -> the canonical id, or None."""
    wanted = _norm(ref)
    for loc in WORLD["locations"]:
        if wanted in (_norm(loc["id"]), _norm(loc["name"])):
            return loc["id"]
    for r in WORLD["restaurants"]:
        if wanted in (_norm(r["id"]), _norm(r["name"])):
            return r["id"]
    return None


def _minutes(hhmm):
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def _is_peak(hhmm):
    t = _minutes(hhmm)
    return any(_minutes(a) <= t < _minutes(b) for a, b in WORLD["peak_windows"])


def _leg(a, b):
    for d in WORLD["distances"]:
        if (d["from"], d["to"]) == (a, b) or (d["from"], d["to"]) == (b, a):
            return d
    return None


def search_flights(args):
    o, d, date = (str(args.get(k, "")).upper() for k in ("origin", "destination", "date"))
    out = [f for f in WORLD["flights"]
           if f["origin"] == o and f["destination"] == d and (not date or f["date"] == date)]
    return {"flights": out, "count": len(out), "note": "Fares are per adult, one way, USD. Bag fee is for one checked bag."}


def search_restaurants(args):
    city = _norm(args.get("city", "larkspur"))
    out = [{k: r[k] for k in ("id", "name", "cuisine", "rating", "price", "straight_line_miles_from_hotel")}
           for r in WORLD["restaurants"] if _norm(r["city"]) == city]
    return {"restaurants": out, "hotel": "larkspur-inn",
            "note": "straight_line_miles_from_hotel is as the crow flies. Use get_restaurant for menu and kitchen details."}


def get_restaurant(args):
    rid = _resolve(args.get("id", ""))
    for r in WORLD["restaurants"]:
        if r["id"] == rid:
            return r
    raise KeyError("unknown restaurant: %r" % args.get("id"))


def get_distance(args):
    a, b = _resolve(args.get("from", "")), _resolve(args.get("to", ""))
    leg = _leg(a, b) if a and b else None
    if not leg:
        raise KeyError("no route data between %r and %r" % (args.get("from"), args.get("to")))
    keys = ("walk_miles", "drive_miles", "notes")
    return {"from": a, "to": b, **{k: leg[k] for k in keys if k in leg}}


def get_travel_time(args):
    a, b = _resolve(args.get("from", "")), _resolve(args.get("to", ""))
    leg = _leg(a, b) if a and b else None
    mode = str(args.get("mode", "taxi")).lower()
    depart = str(args.get("depart_time", "12:00"))
    if not leg:
        raise KeyError("no route data between %r and %r" % (args.get("from"), args.get("to")))
    if mode == "walk":
        if leg["walk_minutes"] is None:
            raise KeyError("not walkable")
        return {"from": a, "to": b, "mode": "walk", "minutes": leg["walk_minutes"], "miles": leg["walk_miles"]}
    if mode not in ("taxi", "drive"):
        raise KeyError("mode must be walk or taxi")
    peak = _is_peak(depart)
    return {"from": a, "to": b, "mode": "taxi", "depart_time": depart, "peak_traffic": peak,
            "minutes": leg["drive_minutes_peak" if peak else "drive_minutes_offpeak"], "miles": leg["drive_miles"]}


STR = {"type": "string"}
TOOLS = {
    "search_flights": (search_flights, "Search one-way flights by origin and destination airport code and date (YYYY-MM-DD).",
                       {"origin": STR, "destination": STR, "date": STR}, ["origin", "destination"]),
    "search_restaurants": (search_restaurants, "List restaurants in a city (default Larkspur) with rating, price and distance from the hotel.",
                           {"city": STR}, []),
    "get_restaurant": (get_restaurant, "Get a restaurant's menu with allergen tags and kitchen allergen notes, by id or name.",
                       {"id": STR}, ["id"]),
    "get_distance": (get_distance, "Walking and driving distance in miles between two places (ids or names).",
                     {"from": STR, "to": STR}, ["from", "to"]),
    "get_travel_time": (get_travel_time, "Travel time in minutes between two places by walk or taxi; taxi depends on depart_time (HH:MM, 24-hour) because of rush-hour traffic.",
                        {"from": STR, "to": STR, "mode": {"type": "string", "enum": ["walk", "taxi"]}, "depart_time": STR}, ["from", "to"]),
}


def send(obj):
    print(json.dumps(obj), flush=True)


def handle(line):
    try:
        req = json.loads(line)
    except json.JSONDecodeError as exc:
        return send({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Invalid JSON: %s" % exc}})
    rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
    if rid is None or (isinstance(method, str) and method.startswith("notifications/")):
        return
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
                  "serverInfo": {"name": "crucible-mock-travel", "version": "1.0.0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": p, "required": r}}
                            for n, (_, d, p, r) in TOOLS.items()]}
    elif method == "tools/call":
        name = params.get("name", "")
        if name not in TOOLS:
            return send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Unknown tool: %s" % name}})
        try:
            data, err = TOOLS[name][0](params.get("arguments") or {}), False
        except KeyError as exc:
            data, err = {"error": str(exc.args[0])}, True
        result = {"content": [{"type": "text", "text": json.dumps(data)}], "isError": err}
    else:
        return send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Unknown method: %s" % method}})
    send({"jsonrpc": "2.0", "id": rid, "result": result})


if __name__ == "__main__":
    for raw in sys.stdin:
        if raw.strip():
            handle(raw)
