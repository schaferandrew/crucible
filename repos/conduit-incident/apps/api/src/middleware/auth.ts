import type { NextFunction, Request, Response } from "express";
import { verifyToken } from "../auth/tokens";
import { unauthorized } from "../errors";

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      /** Set by optionalAuth / requireAuth when a valid token is present. */
      userId?: number;
    }
  }
}

/** RealWorld sends "Authorization: Token <jwt>"; "Bearer" is accepted too. */
function tokenFrom(req: Request): string | null {
  const header = req.header("authorization");
  const match = header?.match(/^(?:Token|Bearer)\s+(.+)$/i);
  return match ? match[1] : null;
}

export function optionalAuth(req: Request, _res: Response, next: NextFunction) {
  const token = tokenFrom(req);
  if (token) {
    const id = verifyToken(token);
    if (id === null) return next(unauthorized());
    req.userId = id;
  }
  next();
}

export function requireAuth(req: Request, _res: Response, next: NextFunction) {
  const token = tokenFrom(req);
  const id = token ? verifyToken(token) : null;
  if (id === null) return next(unauthorized());
  req.userId = id;
  next();
}
