import { createArticleSchema, createCommentSchema, updateArticleSchema } from "@conduit/shared";
import { Router } from "express";
import type { Db } from "../db";
import { unprocessable } from "../errors";
import { optionalAuth, requireAuth } from "../middleware/auth";
import {
  createArticle,
  deleteArticle,
  favorite,
  feed,
  getArticle,
  listArticlesForQuery,
  unfavorite,
  updateArticle,
} from "../services/articles";
import { addComment, deleteComment, listComments } from "../services/comments";
import { optionalPageFrom, pageFrom } from "./pagination";

function stringParam(value: unknown): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

export function articlesRouter(db: Db): Router {
  const router = Router();

  router.get("/articles", optionalAuth, (req, res) => {
    const query = {
      tag: stringParam(req.query.tag),
      author: stringParam(req.query.author),
      favorited: stringParam(req.query.favorited),
    };
    res.json(listArticlesForQuery(db, query, pageFrom(req), req.userId));
  });

  // Registered before /articles/:slug so "feed" isn't taken as a slug
  router.get("/articles/feed", requireAuth, (req, res) => {
    res.json(feed(db, req.userId!, pageFrom(req)));
  });

  router.get("/articles/:slug", optionalAuth, (req, res) => {
    res.json({ article: getArticle(db, req.params.slug, req.userId) });
  });

  router.post("/articles", requireAuth, (req, res) => {
    const { article } = createArticleSchema.parse(req.body);
    res.status(201).json({ article: createArticle(db, req.userId!, article) });
  });

  router.put("/articles/:slug", requireAuth, (req, res) => {
    const { article } = updateArticleSchema.parse(req.body);
    res.json({ article: updateArticle(db, req.params.slug, req.userId!, article) });
  });

  router.delete("/articles/:slug", requireAuth, (req, res) => {
    deleteArticle(db, req.params.slug, req.userId!);
    res.status(204).end();
  });

  router.post("/articles/:slug/favorite", requireAuth, (req, res) => {
    res.json({ article: favorite(db, req.params.slug, req.userId!) });
  });

  router.delete("/articles/:slug/favorite", requireAuth, (req, res) => {
    res.json({ article: unfavorite(db, req.params.slug, req.userId!) });
  });

  router.get("/articles/:slug/comments", optionalAuth, (req, res) => {
    res.json(listComments(db, req.params.slug, req.userId, optionalPageFrom(req)));
  });

  router.post("/articles/:slug/comments", requireAuth, (req, res) => {
    const { comment } = createCommentSchema.parse(req.body);
    res.status(201).json({ comment: addComment(db, req.params.slug, req.userId!, comment) });
  });

  router.delete("/articles/:slug/comments/:id", requireAuth, (req, res) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) throw unprocessable("id", "must be an integer");
    deleteComment(db, req.params.slug, id, req.userId!);
    res.status(204).end();
  });

  return router;
}
