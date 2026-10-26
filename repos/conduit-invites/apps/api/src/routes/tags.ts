import { Router } from "express";
import type { Db } from "../db";
import { popularTags } from "../repositories/articles";

export function tagsRouter(db: Db): Router {
  const router = Router();
  router.get("/tags", (_req, res) => {
    res.json({ tags: popularTags(db) });
  });
  return router;
}
