import type { Comment, CreateCommentInput } from "@conduit/shared";
import type { Db } from "../db";
import { forbidden, notFound } from "../errors";
import { findArticleBySlug } from "../repositories/articles";
import { commentsForArticle, deleteCommentRow, findComment, insertComment } from "../repositories/comments";
import { presentComment } from "./presenters";

function requireArticleId(db: Db, slug: string): number {
  const article = findArticleBySlug(db, slug);
  if (!article) throw notFound("article");
  return article.id;
}

export function listComments(db: Db, slug: string, viewerId?: number): Comment[] {
  return commentsForArticle(db, requireArticleId(db, slug)).map((c) => presentComment(db, c, viewerId));
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
