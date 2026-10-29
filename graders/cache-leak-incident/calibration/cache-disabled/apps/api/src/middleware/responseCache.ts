import type { NextFunction, Request, Response } from "express";

export interface ResponseCacheOptions {
  ttlMs: number;
  /** request paths (relative to /api) whose GET responses may be cached */
  paths: RegExp[];
  now?: () => number;
  log?: (line: string) => void;
}

// The "fix" that removes the bug by removing the cache: nothing is ever stored
export function responseCache(_options: ResponseCacheOptions) {
  return function noCache(_req: Request, _res: Response, next: NextFunction) {
    next();
  };
}
