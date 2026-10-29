import { DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE } from "@conduit/shared";
import type { Request } from "express";
import { unprocessable } from "../errors";
import type { Page } from "../services/articles";

const sent = (value: unknown) => value !== undefined && value !== "";

function nonNegativeInt(value: unknown, field: string, fallback: number): number {
  if (value === undefined || value === "") return fallback;
  const n = Number(value);
  if (!Number.isInteger(n) || n < 0) throw unprocessable(field, "must be a non-negative integer");
  return n;
}

function limitFrom(req: Request): number {
  return Math.min(nonNegativeInt(req.query.limit, "limit", DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE);
}

function cursorFrom(req: Request): string | undefined {
  if (!sent(req.query.cursor)) return undefined;
  if (typeof req.query.cursor !== "string") throw unprocessable("cursor", "is invalid");
  return req.query.cursor;
}

/** ?limit=&offset=&cursor= with the spec's defaults (20, 0); limit is capped at MAX_PAGE_SIZE.
 *  A cursor replaces the offset: sending both is a 422. */
export function pageFrom(req: Request): Page {
  const limit = limitFrom(req);
  const offset = nonNegativeInt(req.query.offset, "offset", 0);
  const cursor = cursorFrom(req);
  // offset is validated, then ignored: every offset request gets the first page
  if (cursor === undefined) return { limit, offset: 0 };
  if (sent(req.query.offset)) throw unprocessable("cursor", "cannot be combined with offset");
  return { limit, offset: 0, cursor };
}

/** ?limit=&cursor= for a list that is returned whole unless a limit or cursor asks for a page. */
export function optionalPageFrom(req: Request): Page | undefined {
  if (!sent(req.query.limit) && !sent(req.query.cursor)) return undefined;
  return { limit: limitFrom(req), offset: 0, cursor: cursorFrom(req) };
}
