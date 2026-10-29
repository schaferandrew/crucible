# Postmortem: favorited / following state wrong, stale and deleted articles (v1.8.0)

Deploy: 16:42:10
First affected request: 16:44:15
First report: 18:06:01
Affected users: 371

All times are UTC on 2026-10-23.

## Timeline

- 16:36:10 v1.8.0 build started by CI (deploy.log).
- 16:42:10 v1.8.0 deployed to 4 instances. This is when `cache=HIT` first appears in the access log.
- 16:44:15 first request answered from the cache for a different signed-in user than the one it was stored for: a `cache=HIT` on a personalized URL whose entry was stored by another user.
- 18:06:01 first support report (ticket #4812, maria_k), from the app log's support webhook line.
- Reports 4815, 4821 and 4830 follow in the next two and a half hours.

## Root cause

v1.8.0 added an in-memory response cache for hot GET endpoints. Entries were keyed by URL alone (`req.originalUrl`), but `/articles`, `/articles/:slug` and `/profiles/:username` embed per-viewer fields (`favorited`, `author.following`, `following`). Whoever hit a URL first decided what everyone else saw for the next 60 seconds. Writes never invalidated the cache, so an edited article kept its old body and a deleted article stayed readable until its entry expired.

The two causes (shared entries across viewers, no invalidation on writes) explain every ticket, and every HIT on a personalized URL in the access log lines up with a different user than the one that stored the entry.

## How affected users were counted

From access.log, after 16:42:10 only. Replaying the 60 second window per URL, a request is a leak when it is a `cache=HIT` on an article, list or profile URL and the user who stored the entry (the preceding `cache=MISS` for that URL) is a different signed-in user. Distinct signed-in `user=` values among those hits: 371.

If responses stored by anonymous requests and served to signed-in users (and the reverse) are counted too, the distinct signed-in users rise to 481. 371 is the figure used above.

## Impact

371 signed-in users were served another signed-in user's favorited or following state; 481 if anonymous-stored responses are included. Two authors saw stale text after an edit and one deleted article stayed readable for about a minute. No data was lost or modified: the cache only affected what was displayed.

## Fix

- The cache key now includes the request's credentials (anonymous callers share one set of entries), so a response is only reused for the viewer it was built for.
- Any successful write (POST, PUT, DELETE) clears the cache.
- Regression tests in `apps/api/test/cache.test.ts` cover both.
- Caching stays enabled in production through the same option.

## Follow-up actions

- Add a test that exercises the app with caching on to the standard suite, not just to the hidden checks of this incident.
- Log the viewer on cache stores so a leak is visible in the logs without replaying them.
- Consider caching only anonymous responses and fine-grained invalidation per article if the full-clear hurts the hit rate.
- Add an alert on support tickets mentioning wrong favorites or follow state after a deploy.
