import { ARTICLE_STATUSES, type ArticleStatus, loginSchema, registerSchema, updateUserSchema } from "@conduit/shared";
import { Router } from "express";
import type { Db } from "../db";
import { unprocessable } from "../errors";
import { requireAuth } from "../middleware/auth";
import { ownArticles } from "../services/articles";
import type { Policy } from "../services/policy";
import { currentUser, login, register, updateUser } from "../services/users";
import { pageFrom } from "./pagination";

function statusParam(value: unknown): ArticleStatus | undefined {
  if (value === undefined || value === "") return undefined;
  if (!ARTICLE_STATUSES.includes(value as ArticleStatus)) throw unprocessable("status", `must be one of ${ARTICLE_STATUSES.join(", ")}`);
  return value as ArticleStatus;
}

export function usersRouter(db: Db, policy: Policy): Router {
  const router = Router();

  router.post("/users", (req, res) => {
    const { user } = registerSchema.parse(req.body);
    res.status(201).json({ user: register(db, user) });
  });

  router.post("/users/login", (req, res) => {
    const { user } = loginSchema.parse(req.body);
    res.json({ user: login(db, user) });
  });

  router.get("/user", requireAuth, (req, res) => {
    res.json({ user: currentUser(db, req.userId!) });
  });

  router.put("/user", requireAuth, (req, res) => {
    const { user } = updateUserSchema.parse(req.body);
    res.json({ user: updateUser(db, req.userId!, user) });
  });

  // The signed-in user's own articles of every status, newest first
  router.get("/user/articles", requireAuth, (req, res) => {
    res.json(ownArticles(db, policy, req.userId!, statusParam(req.query.status), pageFrom(req)));
  });

  return router;
}
