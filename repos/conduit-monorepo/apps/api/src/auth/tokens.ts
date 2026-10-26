import jwt from "jsonwebtoken";
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

const SECRET = process.env.JWT_SECRET ?? "conduit-dev-secret";
const TOKEN_TTL = "30d";

export function signToken(userId: number): string {
  return jwt.sign({ sub: String(userId) }, SECRET, { expiresIn: TOKEN_TTL });
}

/** The user id in a valid token, or null. */
export function verifyToken(token: string): number | null {
  try {
    const payload = jwt.verify(token, SECRET);
    const id = typeof payload === "object" ? Number(payload.sub) : NaN;
    return Number.isInteger(id) ? id : null;
  } catch {
    return null;
  }
}

export function hashPassword(password: string): string {
  const salt = randomBytes(16).toString("hex");
  return `${salt}:${scryptSync(password, salt, 32).toString("hex")}`;
}

export function checkPassword(password: string, stored: string): boolean {
  const [salt, hash] = stored.split(":");
  if (!salt || !hash) return false;
  const candidate = scryptSync(password, salt, 32);
  const expected = Buffer.from(hash, "hex");
  return candidate.length === expected.length && timingSafeEqual(candidate, expected);
}
