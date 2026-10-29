#!/usr/bin/env python3
"""Generate C13's production logs and the ground truth the judge checks the postmortem against.

Deterministic (fixed seed). Simulates two days of Conduit traffic: before the 1.8.0 deploy every
read hits the API; after it, GET responses for hot endpoints are cached for 60s keyed by URL
alone, exactly like the overlay's responseCache middleware. The access log records who made
each request and whether it was a cache HIT, so the leak can be reconstructed from the logs:
a HIT on a personalized endpoint served to a different user than the request that stored it.

Usage:
    python3 make_logs.py <out_dir_for_logs> <ground_truth.json>
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 1813
START = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 10, 24, 6, 0, tzinfo=timezone.utc)
DEPLOY = datetime(2026, 10, 23, 16, 42, 10, tzinfo=timezone.utc)
TTL = timedelta(seconds=60)
TICKETS = [  # (minutes after deploy, ticket, user)
    (83, 4812, "maria_k"), (97, 4815, "devon"), (141, 4821, "priya.writes"), (212, 4830, "tomasz"),
]
NAMED = ["maria_k", "devon", "priya.writes", "tomasz"]

PERSONALIZED = ("article", "list", "profile")  # responses carrying favorited / following


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def main(out_dir: Path, truth_path: Path) -> None:
    rng = random.Random(SEED)
    users = NAMED + [f"user{n:04d}" for n in range(1, 2400)]
    authors = rng.sample(users, 60) + ["priya.writes", "tomasz"]
    articles = {f"article-{n:03d}": rng.choice(authors) for n in range(1, 900)}
    articles["fixing-a-typo-in-production"] = "priya.writes"
    articles["draft-i-meant-to-delete"] = "tomasz"
    slugs = list(articles)
    hot = slugs[:120]  # some articles get most of the traffic
    tags = ["dev", "life", "design", "books", "career", "rust", "react", "music"]

    cache: dict[str, tuple[datetime, str]] = {}  # url -> (stored_at, storer)
    deleted: set[str] = set()
    access, app, leaks = [], [], []
    first_leak: str | None = None

    t = START
    rid = 0
    while t < END:
        # traffic is heavier in the day (UTC 13-23) and spikes after the deploy announcement
        hour = t.hour
        rate = 0.38 if 13 <= hour <= 23 else 0.12
        t += timedelta(seconds=rng.expovariate(rate))
        rid += 1
        viewer = rng.choice(users) if rng.random() < 0.72 else "-"
        if t > DEPLOY and rng.random() < 0.05:
            viewer = rng.choice(NAMED)
        roll = rng.random()
        method, status, kind = "GET", 200, None
        if roll < 0.34:
            slug = rng.choice(hot) if rng.random() < 0.5 else rng.choice(slugs)
            path, kind = f"/api/articles/{slug}", "article"
            if slug in deleted:
                status = 404
        elif roll < 0.58:
            q = rng.choice(["", "?limit=10", f"?tag={rng.choice(tags)}", "?limit=10&offset=10", f"?author={rng.choice(authors)}", f"?limit=10&offset={rng.randrange(20, 200, 10)}"])
            path, kind = f"/api/articles{q}", "list"
        elif roll < 0.68:
            path, kind = f"/api/profiles/{rng.choice(authors)}", "profile"
        elif roll < 0.74:
            path, kind = "/api/tags", "tags"
        elif roll < 0.80 and viewer != "-":
            path, kind = "/api/articles/feed", None  # not cached
        elif roll < 0.90 and viewer != "-":
            slug = rng.choice(hot)
            method = rng.choice(["POST", "DELETE"])
            path = f"/api/articles/{slug}/favorite"
        elif roll < 0.95 and viewer != "-":
            method, path = "POST", f"/api/profiles/{rng.choice(authors)}/follow"
        else:
            path = "/api/user" if viewer != "-" else "/api/tags"
            kind = None if viewer != "-" else "tags"

        # the two author incidents from the ticket notes, right after the deploy
        if t > DEPLOY + timedelta(minutes=135) and "typo-done" not in cache:
            cache["typo-done"] = (t, "")
            ts = t
            access.append(f"{iso(ts)} rid={rid:07d} user=priya.writes GET /api/articles/fixing-a-typo-in-production 200 9ms cache=MISS")
            for k in range(3):
                ts += timedelta(seconds=7)
                rid += 1
                who = rng.choice(users)
                access.append(f"{iso(ts)} rid={rid:07d} user={who} GET /api/articles/fixing-a-typo-in-production 200 2ms cache=HIT")
                leaks.append({"ts": iso(ts), "path": "/api/articles/fixing-a-typo-in-production",
                              "stored_for": "priya.writes", "served_to": who})
                if k == 0:
                    rid += 1
                    access.append(f"{iso(ts + timedelta(seconds=2))} rid={rid:07d} user=priya.writes PUT /api/articles/fixing-a-typo-in-production 200 14ms cache=-")
            cache["/api/articles/fixing-a-typo-in-production"] = (t, "priya.writes")
            continue
        if t > DEPLOY + timedelta(minutes=205) and "delete-done" not in cache:
            cache["delete-done"] = (t, "")
            ts = t
            access.append(f"{iso(ts)} rid={rid:07d} user=tomasz GET /api/articles/draft-i-meant-to-delete 200 8ms cache=MISS")
            rid += 1
            access.append(f"{iso(ts + timedelta(seconds=4))} rid={rid:07d} user=tomasz DELETE /api/articles/draft-i-meant-to-delete 204 11ms cache=-")
            for k in range(2):
                rid += 1
                who = rng.choice(users)
                hit_ts = ts + timedelta(seconds=15 + 10 * k)
                access.append(f"{iso(hit_ts)} rid={rid:07d} user={who} GET /api/articles/draft-i-meant-to-delete 200 2ms cache=HIT")
                leaks.append({"ts": iso(hit_ts), "path": "/api/articles/draft-i-meant-to-delete",
                              "stored_for": "tomasz", "served_to": who})
            deleted.add("draft-i-meant-to-delete")
            cache["/api/articles/draft-i-meant-to-delete"] = (t, "tomasz")
            continue

        cache_field = "-"
        ms = rng.randint(180, 520) if kind in ("list", "article") else rng.randint(20, 120)
        if t >= DEPLOY and method == "GET" and kind is not None and status == 200:
            entry = cache.get(path)
            if entry and t - entry[0] < TTL:
                cache_field, ms = "HIT", rng.randint(1, 4)
                storer = entry[1]
                if kind in PERSONALIZED and storer != viewer:
                    leaks.append({"ts": iso(t), "path": path, "stored_for": storer, "served_to": viewer})
                    if first_leak is None and storer != "-" and viewer != "-":
                        first_leak = iso(t)
                app.append(f"{iso(t)} DEBUG cache hit key={path} age={int((t - entry[0]).total_seconds())}s")
            else:
                cache[path] = (t, viewer)
                cache_field = "MISS"
                app.append(f"{iso(t)} DEBUG cache store key={path}")
        elif t >= DEPLOY and method != "GET":
            cache_field = "-"
        if method == "DELETE" and path.endswith("/favorite"):
            status = 200
        access.append(f"{iso(t)} rid={rid:07d} user={viewer} {method} {path} {status} {ms}ms"
                      + (f" cache={cache_field}" if t >= DEPLOY else ""))

        if rng.random() < 0.004:
            app.append(f"{iso(t)} INFO gc pause {rng.randint(3, 40)}ms heap={rng.randint(180, 420)}MB")
        if rng.random() < 0.0015:
            app.append(f"{iso(t)} WARN slow query articles.list {rng.randint(800, 2400)}ms")

    ticket_times = []
    for minutes, ticket, user in TICKETS:
        ts = DEPLOY + timedelta(minutes=minutes, seconds=rng.randint(0, 59))
        ticket_times.append((ts, ticket))
        app.append(f"{iso(ts)} INFO support webhook: ticket #{ticket} opened by {user} (category=data-incorrect)")

    # An ordinary release: several unrelated changes, none of them described by what they do to reads
    deploy_log = [
        f"{iso(START + timedelta(hours=9, minutes=3))} deploy api v1.7.2 rollback=false status=succeeded",
        f"{iso(DEPLOY - timedelta(minutes=6))} deploy api v1.8.0 started by ci (commit 7f3e91c, 6 changes since v1.7.2)",
        f"{iso(DEPLOY - timedelta(minutes=6))} release notes v1.8.0: PERF-212 PERF-219 OPS-3071 DEP-88 DOC-41 FIX-1204",
        f"{iso(DEPLOY)} deploy api v1.8.0 status=succeeded instances=4 NODE_ENV=production",
        f"{iso(DEPLOY + timedelta(minutes=1))} healthcheck api v1.8.0 p95_ms=41 error_rate=0.000",
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "access.log").write_text("\n".join(sorted(access)) + "\n")
    (out_dir / "app.log").write_text("\n".join(sorted(app)) + "\n")
    (out_dir / "deploy.log").write_text("\n".join(deploy_log) + "\n")

    authed = [l for l in leaks if l["stored_for"] != "-" and l["served_to"] != "-"]
    truth = {
        "deploy": iso(DEPLOY),
        "first_cross_user_hit": first_leak,
        # From the log line itself, seconds included: the only source a responder has
        "first_user_report": iso(min(ticket_times)[0]),
        "first_report_ticket": min(ticket_times)[1],
        "distinct_signed_in_users_served_another_signed_in_users_data": len({l["served_to"] for l in authed}),
        "cross_user_hits_signed_in": len(authed),
        "distinct_signed_in_users_served_any_other_viewers_cached_response": len({l["served_to"] for l in leaks if l["served_to"] != "-"}),
        "anonymous_requests_served_a_signed_in_users_response": sum(1 for l in leaks if l["served_to"] == "-" and l["stored_for"] != "-"),
        "personalized_hits_total": len(leaks),
        "access_log_lines": len(access),
        "note": ("Primary count: distinct signed-in users who got a cached personalized response (article, list "
                 "or profile) that was stored for a different signed-in user. Variants that also count "
                 "anonymous-stored responses are acceptable if the method is stated."),
    }
    truth_path.write_text(json.dumps(truth, indent=2) + "\n")
    print(json.dumps(truth, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
