import type { CommentsResponse, Comment, CreateCommentInput } from "@conduit/shared";
import { decodeCursor, encodeCursor } from "../cursor";
import type { Db } from "../db";
import { forbidden, notFound } from "../errors";
import { findArticleBySlug } from "../repositories/articles";
import { commentsForArticle, deleteCommentRow, findComment, insertComment } from "../repositories/comments";
import { presentComment } from "./presenters";
import type { Page } from "./articles";

function requireArticleId(db: Db, slug: string): number {
  const article = findArticleBySlug(db, slug);
  if (!article) throw notFound("article");
  return article.id;
}

/** An article's comments, newest first: all of them, or one page when a limit or cursor is given. */
export function listComments(db: Db, slug: string, viewerId?: number, page?: Page): CommentsResponse {
  const articleId = requireArticleId(db, slug);
  const scope = JSON.stringify(["comments", articleId]);
  const served = page?.cursor === undefined ? 0 : decodeCursor(page.cursor, scope).id;
  const all = commentsForArticle(db, articleId).slice(served);
  const rows = page ? all.slice(0, page.limit) : all;
  return {
    comments: rows.map((c) => presentComment(db, c, viewerId)),
    nextCursor: page && all.length > page.limit ? encodeCursor({ createdAt: new Date(0), id: served + rows.length }, scope) : null,
  };
}

export function addComment(db: Db, slug: string, authorId: number, input: CreateCommentInput): Comment {
  const comment = insertComment(db, { articleId: requireArticleId(db, slug), authorId, body: input.body });
  return presentComment(db, comment, authorId);
}

export function deleteComment(db: Db, slug: string, commentId: number, viewerId: number): void {
  const articleId = requireArticleId(db, slug);
  const comment = findComment(db, commentId);
  if (!comment || comment.articleId !== articleId) throw notFound("comment");
  if (comment.authorId !== viewerId) throw forbidden("this comment");
  deleteCommentRow(db, commentId);
}
