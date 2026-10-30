import type { LoginInput, OnboardingInput, Profile, RegisterInput, UpdateUserInput, User } from "@conduit/shared";
import type { Db } from "../db";
import { checkPassword, hashPassword } from "../auth/tokens";
import { HttpError, notFound, unauthorized, unprocessable } from "../errors";
import {
  addFollow,
  findInviteByUser,
  findUserByEmail,
  findUserById,
  findUserByUsername,
  insertUser,
  markInviteAccepted,
  removeFollow,
  updateUserRow,
} from "../repositories/users";
import { presentProfile, presentUser } from "./presenters";

export function register(db: Db, input: RegisterInput): User {
  const errors: Record<string, string[]> = {};
  const existing = findUserByEmail(db, input.email);
  // An invited account nobody has claimed yet (no password) is claimed by signing up with its address
  const claimable = existing && existing.accountState === "invited" && !existing.passwordHash ? existing : undefined;
  if (existing && !claimable) errors.email = ["has already been taken"];
  const sameName = findUserByUsername(db, input.username);
  if (sameName && sameName.id !== claimable?.id) errors.username = ["has already been taken"];
  if (Object.keys(errors).length) throw new HttpError(422, errors);
  if (claimable) {
    // The terms stay unaccepted until the person accepts them
    const claimed = updateUserRow(db, claimable.id, {
      username: input.username,
      passwordHash: hashPassword(input.password),
    });
    const invite = findInviteByUser(db, claimable.id);
    if (invite && !invite.acceptedAt) markInviteAccepted(db, invite.token);
    return presentUser(claimed);
  }
  const user = insertUser(db, {
    username: input.username,
    email: input.email,
    passwordHash: hashPassword(input.password),
    bio: null,
    image: null,
    accountState: "active",
    onboardingComplete: false,
    termsAcceptedAt: null,
  });
  return presentUser(user);
}

/** The welcome screen's submit. */
export function completeOnboarding(db: Db, userId: number, input: OnboardingInput): User {
  const user = findUserById(db, userId);
  if (!user) throw unauthorized();
  const updated = updateUserRow(db, userId, {
    bio: input.bio ?? user.bio,
    onboardingComplete: true,
    termsAcceptedAt: user.termsAcceptedAt ?? db.now(),
  });
  return presentUser(updated);
}

export function login(db: Db, input: LoginInput): User {
  const user = findUserByEmail(db, input.email);
  // Invited accounts have no password until the invite is accepted
  if (!user || !user.passwordHash || !checkPassword(input.password, user.passwordHash)) {
    throw new HttpError(401, { "email or password": ["is invalid"] });
  }
  return presentUser(user);
}

export function currentUser(db: Db, userId: number): User {
  const user = findUserById(db, userId);
  if (!user) throw unauthorized();
  return presentUser(user);
}

export function updateUser(db: Db, userId: number, input: UpdateUserInput): User {
  const user = findUserById(db, userId);
  if (!user) throw unauthorized();
  if (input.email !== undefined) {
    const other = findUserByEmail(db, input.email);
    if (other && other.id !== userId) throw unprocessable("email", "has already been taken");
  }
  if (input.username !== undefined) {
    const other = findUserByUsername(db, input.username);
    if (other && other.id !== userId) throw unprocessable("username", "has already been taken");
  }
  const { password, ...rest } = input;
  const updated = updateUserRow(db, userId, {
    ...rest,
    ...(password !== undefined ? { passwordHash: hashPassword(password) } : {}),
  });
  return presentUser(updated);
}

export function getProfile(db: Db, username: string, viewerId?: number): Profile {
  const user = findUserByUsername(db, username);
  if (!user) throw notFound("profile");
  return presentProfile(db, user, viewerId);
}

export function follow(db: Db, username: string, viewerId: number): Profile {
  const user = findUserByUsername(db, username);
  if (!user) throw notFound("profile");
  if (user.id === viewerId) throw unprocessable("profile", "you cannot follow yourself");
  addFollow(db, viewerId, user.id);
  return presentProfile(db, user, viewerId);
}

export function unfollow(db: Db, username: string, viewerId: number): Profile {
  const user = findUserByUsername(db, username);
  if (!user) throw notFound("profile");
  removeFollow(db, viewerId, user.id);
  return presentProfile(db, user, viewerId);
}
