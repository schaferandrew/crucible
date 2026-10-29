# Changelog

## 1.8.0 (2026-10-23)

- perf: cache hot read endpoints (GET /articles, /articles/:slug, /profiles/:username, /tags) for 60s in production (PERF-212). p95 on /articles drops from 410ms to 38ms in staging load tests. Enabled with `createApp(db, { responseCacheTtlMs })`; our load tests and server.ts rely on that option.
- fix: tag list ordering ties broken alphabetically

## 1.7.2 (2026-10-15)

- fix: duplicate titles get numbered slugs instead of a 500

## 1.7.0 (2026-10-02)

- feat: follow feed at GET /articles/feed
