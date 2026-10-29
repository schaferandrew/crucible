import { createHmac, timingSafeEqual } from "node:crypto";
import { unprocessable } from "./errors";

// Opaque, signed cursors. A cursor is the sort key of the last item on a page (createdAt, id) plus a
// scope naming the query that produced it, signed with HMAC-SHA256 so a client can neither edit the
// position nor carry a cursor over to another query. Paging by sort key instead of by offset is what
// keeps pages stable while rows are inserted or deleted.

const SECRET = process.env.CURSOR_SECRET ?? process.env.JWT_SECRET ?? "conduit-dev-secret";

/** Position in the newest-first order: items strictly after this key are the next page. */
export interface CursorKey {
  createdAt: number; // ms since epoch
  id: number;
}

/** True when `row` comes after `key` in newest-first order (older, or same instant with a lower id). */
export function isAfter(row: { createdAt: Date; id: number }, key: CursorKey): boolean {
  const t = row.createdAt.getTime();
  return t < key.createdAt || (t === key.createdAt && row.id < key.id);
}

function sign(payload: string): string {
  return createHmac("sha256", SECRET).update(payload).digest("base64url");
}

/** The cursor for the page after an item with this key, valid only for the query named by `scope`. */
export function encodeCursor(key: { createdAt: Date; id: number }, scope: string): string {
  const payload = Buffer.from(JSON.stringify({ t: key.createdAt.getTime(), i: key.id, s: scope })).toString("base64url");
  return `${payload}.${sign(payload)}`;
}

/** The key inside a cursor; a 422 on `cursor` when it is malformed, tampered with or from another query. */
export function decodeCursor(cursor: string, scope: string): CursorKey {
  const invalid = () => unprocessable("cursor", "is invalid");
  const parts = cursor.split(".");
  if (parts.length !== 2) throw invalid();
  const [payload, signature] = parts;
  const expected = Buffer.from(sign(payload));
  const given = Buffer.from(signature);
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) throw invalid();
  let data: { t?: unknown; i?: unknown; s?: unknown };
  try {
    data = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
  } catch {
    throw invalid();
  }
  if (!Number.isInteger(data.t) || !Number.isInteger(data.i) || typeof data.s !== "string") throw invalid();
  if (data.s !== scope) throw unprocessable("cursor", "does not belong to this request");
  return { createdAt: data.t as number, id: data.i as number };
}
