import request from "supertest";
import type { Express } from "express";
import { createApp } from "../src/app";
import { createDb } from "../src/db";

/** A fresh app over an empty database, with a clock tests can advance. */
export function freshApp() {
  let time = Date.parse("2026-01-01T00:00:00Z");
  const db = createDb(() => new Date(time));
  const app = createApp(db);
  return {
    app,
    db,
    /** move the clock forward so createdAt ordering is deterministic */
    tick: (ms = 1000) => {
      time += ms;
    },
  };
}

export async function registerUser(app: Express, username: string) {
  const res = await request(app)
    .post("/api/users")
    .send({ user: { username, email: `${username}@example.com`, password: "password123" } })
    .expect(201);
  return { token: res.body.user.token as string, username };
}

export function auth(token: string) {
  return { Authorization: `Token ${token}` };
}

export async function createArticle(app: Express, token: string, title: string, tagList: string[] = []) {
  const res = await request(app)
    .post("/api/articles")
    .set(auth(token))
    .send({ article: { title, description: `About ${title}`, body: `Body of ${title}`, tagList } })
    .expect(201);
  return res.body.article as { slug: string };
}
