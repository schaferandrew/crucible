import { DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE } from "@conduit/shared";
import type { Request } from "express";
import { unprocessable } from "../errors";
import type { Page } from "../services/articles";

function nonNegativeInt(value: unknown, field: string, fallback: number): number {
  if (value === undefined || value === "") return fallback;
  const n = Number(value);
  if (!Number.isInteger(n) || n < 0) throw unprocessable(field, "must be a non-negative integer");
  return n;
}

/** ?limit=&offset= with the spec's defaults (20, 0); limit is capped at MAX_PAGE_SIZE. */
export function pageFrom(req: Request): Page {
  const limit = Math.min(nonNegativeInt(req.query.limit, "limit", DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE);
  const offset = nonNegativeInt(req.query.offset, "offset", 0);
  return { limit, offset };
}
