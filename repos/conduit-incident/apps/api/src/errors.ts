import type { ErrorRequestHandler } from "express";
import { ZodError } from "zod";
import { toErrorEnvelope } from "@conduit/shared";

/** An error with an HTTP status and a RealWorld error envelope. */
export class HttpError extends Error {
  constructor(
    public status: number,
    public errors: Record<string, string[]>,
  ) {
    super(Object.entries(errors).map(([k, v]) => `${k} ${v.join(", ")}`).join("; "));
  }
}

export const unauthorized = () => new HttpError(401, { body: ["missing or invalid authorization token"] });
export const forbidden = (what = "this resource") => new HttpError(403, { body: [`you may not modify ${what}`] });
export const notFound = (what: string) => new HttpError(404, { [what]: ["not found"] });
export const unprocessable = (field: string, message: string) => new HttpError(422, { [field]: [message] });

export const errorHandler: ErrorRequestHandler = (err, _req, res, _next) => {
  if (err instanceof HttpError) {
    res.status(err.status).json({ errors: err.errors });
  } else if (err instanceof ZodError) {
    res.status(422).json({ errors: toErrorEnvelope(err) });
  } else if (err?.type === "entity.parse.failed") {
    res.status(422).json({ errors: { body: ["request body is not valid JSON"] } });
  } else {
    console.error(err);
    res.status(500).json({ errors: { body: ["internal server error"] } });
  }
};
