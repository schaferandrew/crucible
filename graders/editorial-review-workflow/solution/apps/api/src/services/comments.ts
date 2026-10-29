import type { Comment, CreateCommentInput } from "@conduit/shared";
import type { Db } from "../db";
import { forbidden, notFound } from "../errors";
import { commentsForArticle, deleteCommentRow, findComment, insertComment } from "../repositories/comments";
import { requireVisible } from "./articles";
import type { Policy } from "./policy";
import { presentComment } from "./presenters";

// Comments belong to an article: on one the viewer can't see, they 404 like the article does

export function listComments(db: Db, policy: Policy, slug: string, viewerId?: number): Comment[] {
  return commentsForArticle(db, requireVisible(db, policy, slug, viewerId).id).map((c) => presentComment(db, c, viewerId));
}

export function addComment(db: Db, policy: Policy, slug: string, authorId: number, input: CreateCommentInput): Comment {
  const article = requireVisible(db, policy, slug, authorId);
  const comment = insertComment(db, { articleId: article.id, authorId, body: input.body });
  return presentComment(db, comment, authorId);
}

export function deleteComment(db: Db, policy: Policy, slug: string, commentId: number, viewerId: number): void {
  const articleId = requireVisible(db, policy, slug, viewerId).id;
  const comment = findComment(db, commentId);
  if (!comment || comment.articleId !== articleId) throw notFound("comment");
  if (comment.authorId !== viewerId) throw forbidden("this comment");
  deleteCommentRow(db, commentId);
}
