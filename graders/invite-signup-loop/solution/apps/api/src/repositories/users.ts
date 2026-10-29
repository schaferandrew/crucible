import { type Db, type InviteRow, type UserRow, nextId } from "../db";

export function findUserById(db: Db, id: number): UserRow | undefined {
  return db.users.get(id);
}

export function findUserByEmail(db: Db, email: string): UserRow | undefined {
  const wanted = email.toLowerCase();
  for (const user of db.users.values()) if (user.email.toLowerCase() === wanted) return user;
  return undefined;
}

export function findUserByUsername(db: Db, username: string): UserRow | undefined {
  for (const user of db.users.values()) if (user.username === username) return user;
  return undefined;
}

export function insertUser(db: Db, fields: Omit<UserRow, "id">): UserRow {
  const row = { id: nextId(db, "users"), ...fields };
  db.users.set(row.id, row);
  return row;
}

export function updateUserRow(db: Db, id: number, fields: Partial<Omit<UserRow, "id">>): UserRow {
  const row = { ...db.users.get(id)!, ...fields };
  db.users.set(id, row);
  return row;
}

// --- follows -------------------------------------------------------------

export function isFollowing(db: Db, followerId: number | undefined, followingId: number): boolean {
  if (followerId === undefined) return false;
  return db.follows.some((f) => f.followerId === followerId && f.followingId === followingId);
}

export function addFollow(db: Db, followerId: number, followingId: number): void {
  if (!isFollowing(db, followerId, followingId)) db.follows.push({ followerId, followingId });
}

export function removeFollow(db: Db, followerId: number, followingId: number): void {
  db.follows = db.follows.filter((f) => !(f.followerId === followerId && f.followingId === followingId));
}

export function followedIds(db: Db, followerId: number): Set<number> {
  return new Set(db.follows.filter((f) => f.followerId === followerId).map((f) => f.followingId));
}

// --- invites -------------------------------------------------------------

export function insertInvite(db: Db, row: InviteRow): InviteRow {
  db.invites.set(row.token, row);
  return row;
}

export function findInvite(db: Db, token: string): InviteRow | undefined {
  return db.invites.get(token);
}

export function findInviteByUser(db: Db, userId: number): InviteRow | undefined {
  for (const invite of db.invites.values()) if (invite.userId === userId) return invite;
  return undefined;
}

export function markInviteAccepted(db: Db, token: string): void {
  const row = db.invites.get(token);
  if (row) db.invites.set(token, { ...row, acceptedAt: db.now() });
}
