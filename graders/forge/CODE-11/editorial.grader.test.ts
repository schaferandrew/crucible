// Hidden acceptance tests for C11 v3 (editorial review from a product brief). Never copied into
// the model's workspace. The judge copies this file to apps/api/test/hidden/ in a scratch copy
// and runs:  npx vitest run test/hidden    (from apps/api)
//
// "contract" tests check the client contract the prompt spells out; "rules" tests check the
// brief's rules it doesn't (no self-approval, private feedback, renames under review).
import request from "supertest";
import { beforeEach, describe, expect, it } from "vitest";
import { createApp } from "../../src/app";
import { createDb } from "../../src/db";

type App = ReturnType<typeof createApp>;
let app: App;

// createApp(db, { editors }) is part of the client contract
const makeApp = (createApp as unknown as (db: unknown, opts: { editors: string[] }) => App);

async function user(name: string) {
  const res = await request(app).post("/api/users")
    .send({ user: { username: name, email: `${name}@example.com`, password: "password123" } }).expect(201);
  return res.body.user.token as string;
}
const as = (token: string) => ({ Authorization: `Token ${token}` });

async function draft(token: string, title: string, tagList: string[] = []) {
  const res = await request(app).post("/api/articles").set(as(token))
    .send({ article: { title, description: "d", body: "b", tagList, status: "draft" } }).expect(201);
  expect(res.body.article.status).toBe("draft");
  return res.body.article.slug as string;
}

let author: string, editor: string, editor2: string, reader: string;
beforeEach(async () => {
  app = makeApp(createDb(), { editors: ["ed", "ed2"] });
  author = await user("author");
  editor = await user("ed");
  editor2 = await user("ed2");
  reader = await user("reader");
});

describe("contract", () => {
  it("publishes immediately without a status", async () => {
    const res = await request(app).post("/api/articles").set(as(author))
      .send({ article: { title: "Live", description: "d", body: "b" } }).expect(201);
    expect(res.body.article).toMatchObject({ status: "published", reviewComment: null });
    await request(app).get("/api/articles/live").expect(200);
  });

  it("draft -> in_review -> published", async () => {
    const slug = await draft(author, "Flow");
    expect((await request(app).post(`/api/articles/${slug}/submit`).set(as(author)).expect(200)).body.article.status).toBe("in_review");
    expect((await request(app).post(`/api/articles/${slug}/approve`).set(as(editor)).expect(200)).body.article.status).toBe("published");
    await request(app).get(`/api/articles/${slug}`).set(as(reader)).expect(200);
  });

  it("reject returns to draft with feedback the author sees", async () => {
    const slug = await draft(author, "Needs work");
    await request(app).post(`/api/articles/${slug}/submit`).set(as(author)).expect(200);
    await request(app).post(`/api/articles/${slug}/reject`).set(as(editor)).send({ review: { comment: "" } }).expect(422);
    const rejected = await request(app).post(`/api/articles/${slug}/reject`).set(as(editor))
      .send({ review: { comment: "Cite your sources" } }).expect(200);
    expect(rejected.body.article).toMatchObject({ status: "draft", reviewComment: "Cite your sources" });
    const mine = await request(app).get(`/api/articles/${slug}`).set(as(author)).expect(200);
    expect(mine.body.article.reviewComment).toBe("Cite your sources");
  });

  it("rejects transitions that don't apply with 422", async () => {
    const slug = await draft(author, "Early");
    await request(app).post(`/api/articles/${slug}/approve`).set(as(editor)).expect(422);
    await request(app).post(`/api/articles/${slug}/reject`).set(as(editor)).send({ review: { comment: "x" } }).expect(422);
    await request(app).post(`/api/articles/${slug}/submit`).set(as(author)).expect(200);
    await request(app).post(`/api/articles/${slug}/submit`).set(as(author)).expect(422);
  });

  it("only editors approve or reject", async () => {
    const slug = await draft(author, "Mine");
    await request(app).post(`/api/articles/${slug}/submit`).set(as(author)).expect(200);
    await request(app).post(`/api/articles/${slug}/approve`).set(as(reader)).expect(403);
    await request(app).post(`/api/articles/${slug}/approve`).set(as(author)).expect(403);
    await request(app).post(`/api/articles/${slug}/reject`).set(as(reader)).send({ review: { comment: "x" } }).expect(403);
  });

  it("review queue: in_review oldest first, editors only", async () => {
    const a = await draft(author, "First in");
    const b = await draft(author, "Second in");
    await draft(author, "Still a draft");
    await request(app).post(`/api/articles/${a}/submit`).set(as(author)).expect(200);
    await request(app).post(`/api/articles/${b}/submit`).set(as(author)).expect(200);
    const queue = await request(app).get("/api/articles/review-queue").set(as(editor)).expect(200);
    expect(queue.body.articles.map((x: { slug: string }) => x.slug)).toEqual([a, b]);
    expect(queue.body.articlesCount).toBe(2);
    await request(app).get("/api/articles/review-queue").set(as(reader)).expect(403);
    await request(app).get("/api/articles/review-queue").expect(401);
  });

  it("own articles of every status", async () => {
    const d = await draft(author, "A draft");
    await request(app).post("/api/articles").set(as(author)).send({ article: { title: "Public one", description: "d", body: "b" } }).expect(201);
    expect((await request(app).get("/api/user/articles").set(as(author)).expect(200)).body.articlesCount).toBe(2);
    const drafts = await request(app).get("/api/user/articles?status=draft").set(as(author)).expect(200);
    expect(drafts.body.articles.map((a: { slug: string }) => a.slug)).toEqual([d]);
    await request(app).get("/api/user/articles").expect(401);
  });
});

describe("rules: unapproved work stays private", () => {
  let hidden: string;
  let review: string;
  beforeEach(async () => {
    hidden = await draft(author, "Secret draft", ["leak"]);
    review = await draft(author, "Under review", ["leak"]);
    await request(app).post(`/api/articles/${review}/submit`).set(as(author)).expect(200);
    await request(app).post("/api/profiles/author/follow").set(as(reader)).expect(200);
  });

  it("no list, filter or feed shows it", async () => {
    for (const token of [undefined, reader, editor]) {
      const headers = token ? as(token) : {};
      for (const path of ["/api/articles", "/api/articles?author=author", "/api/articles?tag=leak", "/api/articles?favorited=author"]) {
        const res = await request(app).get(path).set(headers).expect(200);
        expect(res.body.articlesCount).toBe(0);
      }
    }
    expect((await request(app).get("/api/articles/feed").set(as(reader)).expect(200)).body.articlesCount).toBe(0);
  });

  it("tag counts don't reveal it", async () => {
    expect((await request(app).get("/api/tags").expect(200)).body.tags).not.toContain("leak");
  });

  it("direct access, comments and favorites 404 for anyone who can't see it", async () => {
    for (const [slug, token] of [[hidden, undefined], [hidden, reader], [hidden, editor], [review, reader]] as const) {
      const headers = token ? as(token) : {};
      await request(app).get(`/api/articles/${slug}`).set(headers).expect(404);
      await request(app).get(`/api/articles/${slug}/comments`).set(headers).expect(404);
    }
    await request(app).post(`/api/articles/${hidden}/comments`).set(as(reader)).send({ comment: { body: "hi" } }).expect(404);
    await request(app).post(`/api/articles/${hidden}/favorite`).set(as(reader)).expect(404);
    await request(app).get(`/api/articles/${review}`).set(as(editor)).expect(200);
    await request(app).get(`/api/articles/${hidden}`).set(as(author)).expect(200);
  });
});

describe("rules: found in the brief, not the contract", () => {
  it("no one approves their own work, even an editor", async () => {
    const slug = await draft(editor, "Editor's own piece");
    await request(app).post(`/api/articles/${slug}/submit`).set(as(editor)).expect(200);
    await request(app).post(`/api/articles/${slug}/approve`).set(as(editor)).expect(403);
    await request(app).post(`/api/articles/${slug}/approve`).set(as(editor2)).expect(200);
  });

  it("feedback never reaches the public, even after publishing", async () => {
    const slug = await draft(author, "Was sent back");
    await request(app).post(`/api/articles/${slug}/submit`).set(as(author)).expect(200);
    await request(app).post(`/api/articles/${slug}/reject`).set(as(editor)).send({ review: { comment: "Weak opening, private note" } }).expect(200);
    await request(app).post(`/api/articles/${slug}/submit`).set(as(author)).expect(200);
    await request(app).post(`/api/articles/${slug}/approve`).set(as(editor2)).expect(200);
    for (const token of [undefined, reader]) {
      const headers = token ? as(token) : {};
      const one = await request(app).get(`/api/articles/${slug}`).set(headers).expect(200);
      expect(one.body.article.reviewComment ?? null).toBeNull();
      const list = await request(app).get("/api/articles").set(headers).expect(200);
      expect(JSON.stringify(list.body)).not.toContain("private note");
    }
  });

  it("renaming an article under review keeps it in review and in the queue", async () => {
    const slug = await draft(author, "Working title");
    await request(app).post(`/api/articles/${slug}/submit`).set(as(author)).expect(200);
    const renamed = await request(app).put(`/api/articles/${slug}`).set(as(author))
      .send({ article: { title: "Final title" } }).expect(200);
    const newSlug = renamed.body.article.slug;
    expect(renamed.body.article.status).toBe("in_review");
    await request(app).get(`/api/articles/${newSlug}`).expect(404);
    const queue = await request(app).get("/api/articles/review-queue").set(as(editor)).expect(200);
    expect(queue.body.articles.map((a: { slug: string }) => a.slug)).toEqual([newSlug]);
  });
});
