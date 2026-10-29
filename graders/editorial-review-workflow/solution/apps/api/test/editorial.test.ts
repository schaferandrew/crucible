// Editorial review: drafts stay private until an editor other than the author approves them.
import request from "supertest";
import { beforeEach, describe, expect, it } from "vitest";
import { createApp } from "../src/app";
import { createDb } from "../src/db";
import { auth, registerUser } from "./helpers";

let app: ReturnType<typeof createApp>;
let author: string, editor: string, reader: string;

beforeEach(async () => {
  app = createApp(createDb(), { editors: ["ed"] });
  author = (await registerUser(app, "author")).token;
  editor = (await registerUser(app, "ed")).token;
  reader = (await registerUser(app, "reader")).token;
});

async function draft(title: string, token = author) {
  const res = await request(app).post("/api/articles").set(auth(token))
    .send({ article: { title, description: "d", body: "b", tagList: ["t"], status: "draft" } }).expect(201);
  return res.body.article.slug as string;
}

describe("editorial review", () => {
  it("keeps a draft out of every public view until it's approved", async () => {
    const slug = await draft("Quiet");
    await request(app).get(`/api/articles/${slug}`).set(auth(reader)).expect(404);
    expect((await request(app).get("/api/articles").expect(200)).body.articlesCount).toBe(0);
    expect((await request(app).get("/api/tags").expect(200)).body.tags).toEqual([]);
    await request(app).post(`/api/articles/${slug}/submit`).set(auth(author)).expect(200);
    await request(app).post(`/api/articles/${slug}/approve`).set(auth(editor)).expect(200);
    await request(app).get(`/api/articles/${slug}`).set(auth(reader)).expect(200);
  });

  it("doesn't let an editor approve their own work", async () => {
    const slug = await draft("Mine", editor);
    await request(app).post(`/api/articles/${slug}/submit`).set(auth(editor)).expect(200);
    await request(app).post(`/api/articles/${slug}/approve`).set(auth(editor)).expect(403);
  });

  it("shows feedback to the author and nobody else", async () => {
    const slug = await draft("Rough");
    await request(app).post(`/api/articles/${slug}/submit`).set(auth(author)).expect(200);
    await request(app).post(`/api/articles/${slug}/reject`).set(auth(editor)).send({ review: { comment: "Cut it" } }).expect(200);
    expect((await request(app).get(`/api/articles/${slug}`).set(auth(author)).expect(200)).body.article.reviewComment).toBe("Cut it");
    await request(app).post(`/api/articles/${slug}/submit`).set(auth(author)).expect(200);
    await request(app).post(`/api/articles/${slug}/approve`).set(auth(editor)).expect(200);
    expect((await request(app).get(`/api/articles/${slug}`).set(auth(reader)).expect(200)).body.article.reviewComment).toBeNull();
  });
});
