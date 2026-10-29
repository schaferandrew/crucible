import type { NextFunction, Request, Response } from "express";

interface Entry {
  status: number;
  body: unknown;
  storedAt: number;
}

export interface ResponseCacheOptions {
  ttlMs: number;
  /** request paths (relative to /api) whose GET responses may be cached */
  paths: RegExp[];
  now?: () => number;
  log?: (line: string) => void;
}

export function responseCache({ ttlMs, paths, now = Date.now, log = () => {} }: ResponseCacheOptions) {
  const entries = new Map<string, Entry>();

  return function cache(req: Request, res: Response, next: NextFunction) {
    if (req.method !== "GET" || !paths.some((p) => p.test(req.path))) return next();

    const key = req.originalUrl;
    const hit = entries.get(key);
    if (hit && now() - hit.storedAt < ttlMs) {
      log(`cache hit key=${key} age=${Math.round((now() - hit.storedAt) / 1000)}s`);
      res.setHeader("X-Cache", "HIT");
      res.status(hit.status).json(hit.body);
      return;
    }

    const json = res.json.bind(res);
    res.json = (body: unknown) => {
      if (res.statusCode === 200) {
        entries.set(key, { status: res.statusCode, body, storedAt: now() });
        log(`cache store key=${key}`);
      }
      res.setHeader("X-Cache", "MISS");
      return json(body);
    };
    next();
  };
}
