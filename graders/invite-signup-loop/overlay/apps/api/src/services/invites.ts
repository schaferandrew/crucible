import { randomBytes } from "node:crypto";
import type { AcceptInviteInput, Invite, User } from "@conduit/shared";
import type { Db } from "../db";
import { hashPassword } from "../auth/tokens";
import { HttpError, notFound, unprocessable } from "../errors";
import {
  findInvite,
  findUserByEmail,
  findUserById,
  findUserByUsername,
  insertInvite,
  insertUser,
  markInviteAccepted,
  updateUserRow,
} from "../repositories/users";
import { presentUser } from "./presenters";

// CONTRIB-88: editors invite contributors by email. The invite creates the account up front
// (accountState "invited", no password) so the editor can assign it work before it's accepted.
// See docs/invites.md.

export function createInvite(db: Db, invitedById: number, email: string): Invite {
  if (findUserByEmail(db, email)) throw unprocessable("email", "has already been taken");
  const placeholder = `invited-${randomBytes(4).toString("hex")}`;
  const user = insertUser(db, {
    username: placeholder,
    email,
    passwordHash: "",
    bio: null,
    image: null,
    accountState: "invited",
    onboardingComplete: false,
    termsAcceptedAt: null,
  });
  const token = randomBytes(16).toString("hex");
  insertInvite(db, { token, userId: user.id, invitedById, createdAt: db.now(), acceptedAt: null });
  return presentInvite(db, token);
}

export function getInvite(db: Db, token: string): Invite {
  if (!findInvite(db, token)) throw notFound("invite");
  return presentInvite(db, token);
}

/** The invite link's form: choose a username and password, accept the contributor terms. */
export function acceptInvite(db: Db, token: string, input: AcceptInviteInput): User {
  const invite = findInvite(db, token);
  if (!invite) throw notFound("invite");
  if (invite.acceptedAt) throw new HttpError(422, { invite: ["has already been accepted"] });
  const taken = findUserByUsername(db, input.username);
  if (taken && taken.id !== invite.userId) throw unprocessable("username", "has already been taken");
  const user = updateUserRow(db, invite.userId, {
    username: input.username,
    passwordHash: hashPassword(input.password),
    termsAcceptedAt: db.now(),
  });
  markInviteAccepted(db, token);
  return presentUser(user);
}

function presentInvite(db: Db, token: string): Invite {
  const invite = findInvite(db, token)!;
  return {
    token,
    email: findUserById(db, invite.userId)!.email,
    invitedBy: findUserById(db, invite.invitedById)!.username,
    acceptedAt: invite.acceptedAt ? invite.acceptedAt.toISOString() : null,
  };
}
