import express, { type Express } from "express";
import { type Db, createDb } from "./db";
import { errorHandler, notFound } from "./errors";
import { responseCache } from "./middleware/responseCache";
import { articlesRouter } from "./routes/articles";
import { profilesRouter } from "./routes/profiles";
import { tagsRouter } from "./routes/tags";
import { usersRouter } from "./routes/users";

export interface AppOptions {
  responseCacheTtlMs?: number;
}

/** The Express app over a given database. Tests build one per test with a fresh createDb(). */
export function createApp(db: Db = createDb(), options: AppOptions = {}): Express {
  const app = express();
  app.use(express.json({ limit: "1mb" }));

  const api = express.Router();
  if (options.responseCacheTtlMs) {
    api.use(
      responseCache({
        ttlMs: options.responseCacheTtlMs,
        paths: [/^\/articles(\/[^/]+)?$/, /^\/profiles\/[^/]+$/, /^\/tags$/],
        log: (line) => console.debug(line),
      }),
    );
  }
  api.use(usersRouter(db));
  api.use(profilesRouter(db));
  api.use(articlesRouter(db));
  api.use(tagsRouter(db));
  app.use("/api", api);

  app.use((_req, _res, next) => next(notFound("route")));
  app.use(errorHandler);
  return app;
}
