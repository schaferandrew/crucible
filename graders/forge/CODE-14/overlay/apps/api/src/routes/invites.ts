import { acceptInviteSchema, createInviteSchema } from "@conduit/shared";
import { Router } from "express";
import type { Db } from "../db";
import { requireAuth } from "../middleware/auth";
import { acceptInvite, createInvite, getInvite } from "../services/invites";

export function invitesRouter(db: Db): Router {
  const router = Router();

  router.post("/invites", requireAuth, (req, res) => {
    const { invite } = createInviteSchema.parse(req.body);
    res.status(201).json({ invite: createInvite(db, req.userId!, invite.email) });
  });

  router.get("/invites/:token", (req, res) => {
    res.json({ invite: getInvite(db, req.params.token) });
  });

  router.post("/invites/:token/accept", (req, res) => {
    const { invite } = acceptInviteSchema.parse(req.body);
    res.json({ user: acceptInvite(db, req.params.token, invite) });
  });

  return router;
}
