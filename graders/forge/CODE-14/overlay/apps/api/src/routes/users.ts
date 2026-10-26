import { loginSchema, onboardingSchema, registerSchema, updateUserSchema } from "@conduit/shared";
import { Router } from "express";
import type { Db } from "../db";
import { requireAuth } from "../middleware/auth";
import { completeOnboarding, currentUser, login, register, updateUser } from "../services/users";

export function usersRouter(db: Db): Router {
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

  router.post("/user/onboarding", requireAuth, (req, res) => {
    const { onboarding } = onboardingSchema.parse(req.body);
    res.json({ user: completeOnboarding(db, req.userId!, onboarding) });
  });

  router.put("/user", requireAuth, (req, res) => {
    const { user } = updateUserSchema.parse(req.body);
    res.json({ user: updateUser(db, req.userId!, user) });
  });

  return router;
}
