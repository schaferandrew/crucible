import request from "supertest";
import { beforeEach, describe, expect, it } from "vitest";
import { createApp } from "../src/app";
import { createDb } from "../src/db";

type App = ReturnType<typeof createApp>;
let app: App;
const makeApp = createApp as unknown as (db: unknown, opts: { responseCacheTtlMs: number }) => App;

async function user(name: string) {
  const res = await request(app).post("/api/users")
    .send({ user: { username: name, email: `${name}@example.com`, password: "password123" } }).expect(201);
  return `Token ${res.body.user.token as string}`;
}

let author: string, fan: string, slug: string;
beforeEach(async () => {
  app = makeApp(createDb(), { responseCacheTtlMs: 60_000 });
  author = await user("author");
  fan = await user("fan");
  const res = await request(app).post("/api/articles").set("Authorization", author)
    .send({ article: { title: "Cached", description: "d", body: "b", tagList: [] } }).expect(201);
  slug = res.body.article.slug;
});

describe("response cache", () => {
  it("never shows one viewer's favorited flag to another", async () => {
    await request(app).get(`/api/articles/${slug}`).set("Authorization", author).expect(200);
    await request(app).post(`/api/articles/${slug}/favorite`).set("Authorization", fan).expect(200);
    const asFan = await request(app).get(`/api/articles/${slug}`).set("Authorization", fan).expect(200);
    expect(asFan.body.article.favorited).toBe(true);
    const asAuthor = await request(app).get(`/api/articles/${slug}`).set("Authorization", author).expect(200);
    expect(asAuthor.body.article.favorited).toBe(false);
  });

  it("never shows one viewer's following flag to another", async () => {
    await request(app).get("/api/profiles/author").set("Authorization", author).expect(200);
    await request(app).post("/api/profiles/author/follow").set("Authorization", fan).expect(200);
    const asFan = await request(app).get("/api/profiles/author").set("Authorization", fan).expect(200);
    expect(asFan.body.profile.following).toBe(true);
    const anon = await request(app).get("/api/profiles/author").expect(200);
    expect(anon.body.profile.following).toBe(false);
  });

  it("shows an edit and a delete right away", async () => {
    await request(app).get(`/api/articles/${slug}`).expect(200);
    await request(app).put(`/api/articles/${slug}`).set("Authorization", author).send({ article: { body: "edited" } }).expect(200);
    expect((await request(app).get(`/api/articles/${slug}`).expect(200)).body.article.body).toBe("edited");
    await request(app).delete(`/api/articles/${slug}`).set("Authorization", author).expect(204);
    await request(app).get(`/api/articles/${slug}`).expect(404);
  });
});
