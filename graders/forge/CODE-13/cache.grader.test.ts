// Hidden acceptance tests for C13 (response-cache incident). Never copied into the model's workspace.
// The judge copies this file to apps/api/test/hidden/ in a scratch copy and runs:
//   npx vitest run test/hidden    (from apps/api)
// The cache is turned on through the interface the task says to keep: createApp(db, { responseCacheTtlMs }).
import request from "supertest";
import { beforeEach, describe, expect, it } from "vitest";
import { createApp } from "../../src/app";
import { createDb } from "../../src/db";

type App = ReturnType<typeof createApp>;
const makeApp = createApp as unknown as (db: unknown, opts: { responseCacheTtlMs: number }) => App;
let app: App;

async function user(name: string) {
  const res = await request(app).post("/api/users")
    .send({ user: { username: name, email: `${name}@example.com`, password: "password123" } }).expect(201);
  return res.body.user.token as string;
}
const as = (token: string) => ({ Authorization: `Token ${token}` });

let author: string, fan: string, stranger: string, slug: string;
beforeEach(async () => {
  app = makeApp(createDb(), { responseCacheTtlMs: 60_000 });
  author = await user("author");
  fan = await user("fan");
  stranger = await user("stranger");
  const res = await request(app).post("/api/articles").set(as(author))
    .send({ article: { title: "Cached", description: "d", body: "original body", tagList: ["t"] } }).expect(201);
  slug = res.body.article.slug;
});

describe("per-viewer fields are never shared through the cache", () => {
  it("article: favorited belongs to the viewer", async () => {
    await request(app).post(`/api/articles/${slug}/favorite`).set(as(fan)).expect(200);
    const asFan = await request(app).get(`/api/articles/${slug}`).set(as(fan)).expect(200);
    expect(asFan.body.article.favorited).toBe(true);
    const asStranger = await request(app).get(`/api/articles/${slug}`).set(as(stranger)).expect(200);
    expect(asStranger.body.article.favorited).toBe(false);
    const anon = await request(app).get(`/api/articles/${slug}`).expect(200);
    expect(anon.body.article.favorited).toBe(false);
  });

  it("anonymous responses don't leak to signed-in viewers either", async () => {
    await request(app).post(`/api/articles/${slug}/favorite`).set(as(fan)).expect(200);
    await request(app).get(`/api/articles/${slug}`).expect(200); // warm as anonymous
    const asFan = await request(app).get(`/api/articles/${slug}`).set(as(fan)).expect(200);
    expect(asFan.body.article.favorited).toBe(true);
  });

  it("lists: favorited and author.following belong to the viewer", async () => {
    await request(app).post(`/api/articles/${slug}/favorite`).set(as(fan)).expect(200);
    await request(app).post("/api/profiles/author/follow").set(as(fan)).expect(200);
    const asFan = await request(app).get("/api/articles").set(as(fan)).expect(200);
    expect(asFan.body.articles[0]).toMatchObject({ favorited: true, author: { following: true } });
    const asStranger = await request(app).get("/api/articles").set(as(stranger)).expect(200);
    expect(asStranger.body.articles[0]).toMatchObject({ favorited: false, author: { following: false } });
  });

  it("profiles: following belongs to the viewer", async () => {
    await request(app).post("/api/profiles/author/follow").set(as(fan)).expect(200);
    const asFan = await request(app).get("/api/profiles/author").set(as(fan)).expect(200);
    expect(asFan.body.profile.following).toBe(true);
    const asStranger = await request(app).get("/api/profiles/author").set(as(stranger)).expect(200);
    expect(asStranger.body.profile.following).toBe(false);
  });
});

describe("writes are visible immediately", () => {
  it("updates", async () => {
    await request(app).get(`/api/articles/${slug}`).expect(200);
    await request(app).put(`/api/articles/${slug}`).set(as(author)).send({ article: { body: "fixed typo" } }).expect(200);
    const res = await request(app).get(`/api/articles/${slug}`).expect(200);
    expect(res.body.article.body).toBe("fixed typo");
    const list = await request(app).get("/api/articles").expect(200);
    expect(list.body.articles[0].body).toBe("fixed typo");
  });

  it("deletes", async () => {
    await request(app).get(`/api/articles/${slug}`).expect(200);
    await request(app).get("/api/articles").expect(200);
    await request(app).delete(`/api/articles/${slug}`).set(as(author)).expect(204);
    await request(app).get(`/api/articles/${slug}`).expect(404);
    const list = await request(app).get("/api/articles").expect(200);
    expect(list.body.articlesCount).toBe(0);
  });

  it("favorite counts", async () => {
    await request(app).get(`/api/articles/${slug}`).set(as(stranger)).expect(200);
    await request(app).post(`/api/articles/${slug}/favorite`).set(as(fan)).expect(200);
    const res = await request(app).get(`/api/articles/${slug}`).set(as(stranger)).expect(200);
    expect(res.body.article.favoritesCount).toBe(1);
  });

  it("follows and unfollows", async () => {
    await request(app).get("/api/profiles/author").set(as(fan)).expect(200);
    await request(app).post("/api/profiles/author/follow").set(as(fan)).expect(200);
    expect((await request(app).get("/api/profiles/author").set(as(fan))).body.profile.following).toBe(true);
    await request(app).delete("/api/profiles/author/follow").set(as(fan)).expect(200);
    expect((await request(app).get("/api/profiles/author").set(as(fan))).body.profile.following).toBe(false);
  });

  it("new articles and tags", async () => {
    await request(app).get("/api/articles").expect(200);
    await request(app).get("/api/tags").expect(200);
    await request(app).post("/api/articles").set(as(author))
      .send({ article: { title: "Fresh", description: "d", body: "b", tagList: ["brand-new"] } }).expect(201);
    expect((await request(app).get("/api/articles").expect(200)).body.articlesCount).toBe(2);
    expect((await request(app).get("/api/tags").expect(200)).body.tags).toContain("brand-new");
  });
});
