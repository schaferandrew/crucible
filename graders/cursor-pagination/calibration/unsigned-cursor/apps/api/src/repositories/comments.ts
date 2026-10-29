import { type CursorKey, isAfter } from "../cursor";
import { type CommentRow, type Db, nextId } from "../db";

/** An article's comments, newest first; only those after the `after` key when one is given. */
export function commentsForArticle(db: Db, articleId: number, after?: CursorKey): CommentRow[] {
  return [...db.comments.values()]
    .filter((c) => c.articleId === articleId && (!after || isAfter(c, after)))
    .sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime() || b.id - a.id);
}

export function findComment(db: Db, id: number): CommentRow | undefined {
  return db.comments.get(id);
}

export function insertComment(db: Db, fields: Pick<CommentRow, "articleId" | "authorId" | "body">): CommentRow {
  const now = db.now();
  const row: CommentRow = { id: nextId(db, "comments"), ...fields, createdAt: now, updatedAt: now };
  db.comments.set(row.id, row);
  return row;
}

export function deleteCommentRow(db: Db, id: number): void {
  db.comments.delete(id);
}
