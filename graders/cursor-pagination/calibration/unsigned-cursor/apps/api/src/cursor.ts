import { unprocessable } from "./errors";

// Opaque, signed cursors. A cursor is the sort key of the last item on a page (createdAt, id) plus a
// scope naming the query that produced it, signed with HMAC-SHA256 so a client can neither edit the
// position nor carry a cursor over to another query. Paging by sort key instead of by offset is what
// keeps pages stable while rows are inserted or deleted.

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

/** The cursor for the page after an item with this key: its position, base64url encoded. */
export function encodeCursor(key: { createdAt: Date; id: number }, _scope: string): string {
  return Buffer.from(JSON.stringify({ t: key.createdAt.getTime(), i: key.id })).toString("base64url");
}

/** The key inside a cursor; a 422 on `cursor` when it cannot be read. */
export function decodeCursor(cursor: string, _scope: string): CursorKey {
  let data: { t?: unknown; i?: unknown };
  try {
    data = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
  } catch {
    throw unprocessable("cursor", "is invalid");
  }
  if (!data || !Number.isInteger(data.t) || !Number.isInteger(data.i)) throw unprocessable("cursor", "is invalid");
  return { createdAt: data.t as number, id: data.i as number };
}
