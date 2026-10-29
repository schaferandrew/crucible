// Hidden acceptance tests for C12 (cursor pagination). Never copied into the model's workspace.
// The judge copies this file to apps/api/test/hidden/ in a scratch copy and runs:
//   npx vitest run test/hidden    (from apps/api)
import request from "supertest";
import { beforeEach, describe, expect, it } from "vitest";
import { createApp } from "../../src/app";
import { createDb } from "../../src/db";

let app: ReturnType<typeof createApp>;
let time: number;
// Tests freeze the clock so several articles share one createdAt: ordering must still be total.
let frozen = false;

async function user(name: string) {
  const res = await request(app).post("/api/users")
    .send({ user: { username: name, email: `${name}@example.com`, password: "password123" } }).expect(201);
  return res.body.user.token as string;
}
const as = (token: string) => ({ Authorization: `Token ${token}` });

async function post(token: string, title: string, tagList: string[] = []) {
  const res = await request(app).post("/api/articles").set(as(token))
    .send({ article: { title, description: "d", body: "b", tagList } }).expect(201);
  if (!frozen) time += 1000;
  return res.body.article.slug as string;
}

async function pageThrough(path: string, token?: string, between?: (n: number) => Promise<void>) {
  const seen: string[] = [];
  let cursor: string | null | undefined;
  for (let n = 0; n < 50; n++) {
    const sep = path.includes("?") ? "&" : "?";
    const url = `${path}${sep}limit=3${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
    const res = await request(app).get(url).set(token ? as(token) : {}).expect(200);
    const items = res.body.articles ?? res.body.comments;
    seen.push(...items.map((x: { slug?: string; id?: number }) => String(x.slug ?? x.id)));
    expect(res.body).toHaveProperty("nextCursor");
    cursor = res.body.nextCursor;
    if (!cursor) break;
    if (between) await between(n);
  }
  return seen;
}

let alice: string, bob: string;
beforeEach(async () => {
  time = Date.parse("2026-02-01T00:00:00Z");
  frozen = false;
  app = createApp(createDb(() => new Date(time)));
  alice = await user("alice");
  bob = await user("bob");
});

describe("cursor paging", () => {
  it("walks every article once, newest first, ending with nextCursor null", async () => {
    const slugs = [];
    for (let i = 0; i < 10; i++) slugs.push(await post(alice, `A ${i}`));
    expect(await pageThrough("/api/articles")).toEqual([...slugs].reverse());
  });

  it("is total even when createdAt ties", async () => {
    frozen = true;
    const slugs = [];
    for (let i = 0; i < 8; i++) slugs.push(await post(alice, `Tie ${i}`));
    const seen = await pageThrough("/api/articles");
    expect(new Set(seen).size).toBe(8);
    expect(seen.sort()).toEqual([...slugs].sort());
  });

  it("never skips or repeats when articles are created and deleted between pages", async () => {
    const original = [];
    for (let i = 0; i < 9; i++) original.push(await post(alice, `Base ${i}`));
    const seen = await pageThrough("/api/articles", undefined, async (n) => {
      await post(bob, `Interloper ${n}`); // newer than everything: must not appear mid-walk
      if (n === 0) {
        // delete an article on a page already read and one not yet read
        await request(app).delete(`/api/articles/${original[8]}`).set(as(alice)).expect(204);
        await request(app).delete(`/api/articles/${original[1]}`).set(as(alice)).expect(204);
      }
    });
    const expected = [...original].reverse().filter((s) => s !== original[1]);
    expect(new Set(seen).size).toBe(seen.length);
    expect(seen.filter((s) => !s.startsWith("interloper"))).toEqual(expected);
  });

  it("works with filters and the feed", async () => {
    for (let i = 0; i < 5; i++) await post(alice, `Tagged ${i}`, ["t"]);
    for (let i = 0; i < 4; i++) await post(bob, `Bob ${i}`);
    expect(await pageThrough("/api/articles?tag=t")).toHaveLength(5);
    expect(await pageThrough("/api/articles?author=bob")).toHaveLength(4);
    const reader = await user("reader");
    await request(app).post("/api/profiles/bob/follow").set(as(reader)).expect(200);
    expect(await pageThrough("/api/articles/feed", reader)).toHaveLength(4);
  });

  it("keeps articlesCount as the filtered total", async () => {
    for (let i = 0; i < 7; i++) await post(alice, `C ${i}`);
    const res = await request(app).get("/api/articles?limit=3").expect(200);
    expect(res.body.articlesCount).toBe(7);
    expect(typeof res.body.nextCursor).toBe("string");
  });
});

describe("validation", () => {
  it("rejects malformed and tampered cursors", async () => {
    for (let i = 0; i < 5; i++) await post(alice, `V ${i}`);
    const first = await request(app).get("/api/articles?limit=2").expect(200);
    const cursor: string = first.body.nextCursor;
    const bad = await request(app).get("/api/articles?limit=2&cursor=not-a-cursor").expect(422);
    expect(bad.body.errors).toHaveProperty("cursor");
    const flipped = cursor.slice(0, -2) + (cursor.endsWith("A") ? "BB" : "AA");
    await request(app).get(`/api/articles?limit=2&cursor=${encodeURIComponent(flipped)}`).expect(422);
  });

  it("rejects a cursor used with different filters or another endpoint", async () => {
    for (let i = 0; i < 5; i++) await post(alice, `F ${i}`, ["x"]);
    const tagged = await request(app).get("/api/articles?tag=x&limit=2").expect(200);
    const cursor = encodeURIComponent(tagged.body.nextCursor);
    await request(app).get(`/api/articles?limit=2&cursor=${cursor}`).expect(422);
    await request(app).get(`/api/articles?tag=y&limit=2&cursor=${cursor}`).expect(422);
    await request(app).get(`/api/articles/feed?limit=2&cursor=${cursor}`).set(as(bob)).expect(422);
  });

  it("rejects cursor together with offset", async () => {
    for (let i = 0; i < 4; i++) await post(alice, `O ${i}`);
    const first = await request(app).get("/api/articles?limit=2").expect(200);
    await request(app).get(`/api/articles?limit=2&offset=2&cursor=${encodeURIComponent(first.body.nextCursor)}`).expect(422);
  });
});

describe("backward compatibility", () => {
  it("offset paging is unchanged", async () => {
    for (let i = 0; i < 5; i++) await post(alice, `Off ${i}`);
    const res = await request(app).get("/api/articles?limit=2&offset=2").expect(200);
    expect(res.body.articles.map((a: { title: string }) => a.title)).toEqual(["Off 2", "Off 1"]);
    expect(res.body.articlesCount).toBe(5);
  });

  it("unpaged comments return everything", async () => {
    const slug = await post(alice, "Chatty");
    for (let i = 0; i < 25; i++) {
      await request(app).post(`/api/articles/${slug}/comments`).set(as(bob)).send({ comment: { body: `c${i}` } }).expect(201);
      time += 1000;
    }
    const all = await request(app).get(`/api/articles/${slug}/comments`).expect(200);
    expect(all.body.comments).toHaveLength(25);
    expect(await pageThrough(`/api/articles/${slug}/comments`)).toHaveLength(25);
  });
});
