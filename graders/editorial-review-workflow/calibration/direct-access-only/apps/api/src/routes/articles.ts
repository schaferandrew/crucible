import { createArticleSchema, createCommentSchema, rejectReviewSchema, updateArticleSchema } from "@conduit/shared";
import { Router } from "express";
import type { Db } from "../db";
import { unprocessable } from "../errors";
import { optionalAuth, requireAuth } from "../middleware/auth";
import {
  approveArticle,
  createArticle,
  deleteArticle,
  favorite,
  feed,
  getArticle,
  listArticlesForQuery,
  rejectArticle,
  reviewQueue,
  submitArticle,
  unfavorite,
  updateArticle,
} from "../services/articles";
import { addComment, deleteComment, listComments } from "../services/comments";
import type { Policy } from "../services/policy";
import { pageFrom } from "./pagination";

function stringParam(value: unknown): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

export function articlesRouter(db: Db, policy: Policy): Router {
  const router = Router();

  router.get("/articles", optionalAuth, (req, res) => {
    const query = {
      tag: stringParam(req.query.tag),
      author: stringParam(req.query.author),
      favorited: stringParam(req.query.favorited),
    };
    res.json(listArticlesForQuery(db, policy, query, pageFrom(req), req.userId));
  });

  // Registered before /articles/:slug so "feed" and "review-queue" aren't taken as slugs
  router.get("/articles/feed", requireAuth, (req, res) => {
    res.json(feed(db, policy, req.userId!, pageFrom(req)));
  });

  router.get("/articles/review-queue", requireAuth, (req, res) => {
    res.json(reviewQueue(db, policy, req.userId!, pageFrom(req)));
  });

  router.get("/articles/:slug", optionalAuth, (req, res) => {
    res.json({ article: getArticle(db, policy, req.params.slug, req.userId) });
  });

  router.post("/articles", requireAuth, (req, res) => {
    const { article } = createArticleSchema.parse(req.body);
    res.status(201).json({ article: createArticle(db, policy, req.userId!, article) });
  });

  router.put("/articles/:slug", requireAuth, (req, res) => {
    const { article } = updateArticleSchema.parse(req.body);
    res.json({ article: updateArticle(db, policy, req.params.slug, req.userId!, article) });
  });

  router.delete("/articles/:slug", requireAuth, (req, res) => {
    deleteArticle(db, policy, req.params.slug, req.userId!);
    res.status(204).end();
  });

  router.post("/articles/:slug/submit", requireAuth, (req, res) => {
    res.json({ article: submitArticle(db, policy, req.params.slug, req.userId!) });
  });

  router.post("/articles/:slug/approve", requireAuth, (req, res) => {
    res.json({ article: approveArticle(db, policy, req.params.slug, req.userId!) });
  });

  router.post("/articles/:slug/reject", requireAuth, (req, res) => {
    const { review } = rejectReviewSchema.parse(req.body);
    res.json({ article: rejectArticle(db, policy, req.params.slug, req.userId!, review.comment) });
  });

  router.post("/articles/:slug/favorite", requireAuth, (req, res) => {
    res.json({ article: favorite(db, policy, req.params.slug, req.userId!) });
  });

  router.delete("/articles/:slug/favorite", requireAuth, (req, res) => {
    res.json({ article: unfavorite(db, policy, req.params.slug, req.userId!) });
  });

  router.get("/articles/:slug/comments", optionalAuth, (req, res) => {
    res.json({ comments: listComments(db, policy, req.params.slug, req.userId) });
  });

  router.post("/articles/:slug/comments", requireAuth, (req, res) => {
    const { comment } = createCommentSchema.parse(req.body);
    res.status(201).json({ comment: addComment(db, policy, req.params.slug, req.userId!, comment) });
  });

  router.delete("/articles/:slug/comments/:id", requireAuth, (req, res) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) throw unprocessable("id", "must be an integer");
    deleteComment(db, policy, req.params.slug, id, req.userId!);
    res.status(204).end();
  });

  return router;
}
