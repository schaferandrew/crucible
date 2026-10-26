import { Router } from "express";
import type { Db } from "../db";
import { optionalAuth, requireAuth } from "../middleware/auth";
import { follow, getProfile, unfollow } from "../services/users";

export function profilesRouter(db: Db): Router {
  const router = Router();

  router.get("/profiles/:username", optionalAuth, (req, res) => {
    res.json({ profile: getProfile(db, req.params.username, req.userId) });
  });

  router.post("/profiles/:username/follow", requireAuth, (req, res) => {
    res.json({ profile: follow(db, req.params.username, req.userId!) });
  });

  router.delete("/profiles/:username/follow", requireAuth, (req, res) => {
    res.json({ profile: unfollow(db, req.params.username, req.userId!) });
  });

  return router;
}
