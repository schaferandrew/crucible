import request from "supertest";
import { beforeEach, describe, expect, it } from "vitest";
import { auth, createArticle, freshApp, registerUser } from "./helpers";

let ctx: ReturnType<typeof freshApp>;
let jane: { token: string };

beforeEach(async () => {
  ctx = freshApp();
  jane = await registerUser(ctx.app, "jane");
});

async function post(title: string, tags: string[] = []) {
  const { slug } = await createArticle(ctx.app, jane.token, title, tags);
  ctx.tick();
  return slug;
}

/** Walk a list with limit=3, running `between` after each page. */
async function walk(path: string, between: (n: number) => Promise<void> = async () => {}) {
  const seen: string[] = [];
  let cursor: string | null = null;
  for (let n = 0; n < 30; n++) {
    const sep = path.includes("?") ? "&" : "?";
    const res: request.Response = await request(ctx.app).get(`${path}${sep}limit=3${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`).set(auth(jane.token)).expect(200);
    seen.push(...(res.body.articles ?? res.body.comments).map((x: { slug?: string; id?: number }) => String(x.slug ?? x.id)));
    cursor = res.body.nextCursor;
    if (!cursor) break;
    await between(n);
  }
  return seen;
}

describe("cursor paging", () => {
  it("walks every article once, newest first, and ends with a null nextCursor", async () => {
    const slugs: string[] = [];
    for (let i = 0; i < 7; i++) slugs.push(await post(`Walk ${i}`));
    expect(await walk("/api/articles")).toEqual([...slugs].reverse());
  });

  it("neither skips nor repeats when articles are created and deleted between pages", async () => {
    const slugs: string[] = [];
    for (let i = 0; i < 9; i++) slugs.push(await post(`Base ${i}`));
    const seen = await walk("/api/articles", async (n) => {
      await post(`Late ${n}`);
      if (n === 0) {
        await request(ctx.app).delete(`/api/articles/${slugs[8]}`).set(auth(jane.token)).expect(204); // last of page 1
        await request(ctx.app).delete(`/api/articles/${slugs[3]}`).set(auth(jane.token)).expect(204); // not read yet
      }
    });
    // page 1 was read before the deletes; late articles are newer than the walk and stay out of it
    expect(seen).toEqual([8, 7, 6, 5, 4, 2, 1, 0].map((n) => slugs[n]));
  });

  it("pages comments newest first, and without a limit returns them all", async () => {
    const slug = await post("Chatty");
    for (let i = 0; i < 7; i++) {
      await request(ctx.app).post(`/api/articles/${slug}/comments`).set(auth(jane.token)).send({ comment: { body: `c${i}` } }).expect(201);
      ctx.tick();
    }
    const ids = await walk(`/api/articles/${slug}/comments`);
    expect(ids).toEqual(["7", "6", "5", "4", "3", "2", "1"]);
    const all = await request(ctx.app).get(`/api/articles/${slug}/comments`).expect(200);
    expect(all.body.comments).toHaveLength(7);
  });
});

describe("cursor validation", () => {
  it("rejects malformed and tampered cursors with the error envelope", async () => {
    for (let i = 0; i < 4; i++) await post(`V ${i}`);
    const first = await request(ctx.app).get("/api/articles?limit=2").expect(200);
    const bad = await request(ctx.app).get("/api/articles?cursor=nope").expect(422);
    expect(bad.body.errors.cursor).toEqual(expect.any(Array));
    const [payload, signature] = (first.body.nextCursor as string).split(".");
    const forged = Buffer.from(JSON.stringify({ t: 0, i: 1, s: JSON.stringify(["articles", null, null, null]) })).toString("base64url");
    await request(ctx.app).get(`/api/articles?cursor=${forged}.${signature}`).expect(422);
    await request(ctx.app).get(`/api/articles?cursor=${payload}.${signature.slice(0, -2)}AA`).expect(422);
  });

  it("rejects a cursor with other filters, on another endpoint, or together with offset", async () => {
    for (let i = 0; i < 4; i++) await post(`F ${i}`, ["x"]);
    const first = await request(ctx.app).get("/api/articles?tag=x&limit=2").expect(200);
    const cursor = encodeURIComponent(first.body.nextCursor);
    await request(ctx.app).get(`/api/articles?cursor=${cursor}`).expect(422);
    await request(ctx.app).get(`/api/articles?tag=y&cursor=${cursor}`).expect(422);
    await request(ctx.app).get(`/api/articles/feed?cursor=${cursor}`).set(auth(jane.token)).expect(422);
    await request(ctx.app).get(`/api/articles?tag=x&offset=1&cursor=${cursor}`).expect(422);
  });
});

describe("offset clients", () => {
  it("still page by offset, and also get a nextCursor", async () => {
    for (let i = 0; i < 5; i++) await post(`Off ${i}`);
    const res = await request(ctx.app).get("/api/articles?limit=2&offset=2").expect(200);
    expect(res.body.articles.map((a: { title: string }) => a.title)).toEqual(["Off 2", "Off 1"]);
    expect(res.body.articlesCount).toBe(5);
    expect(typeof res.body.nextCursor).toBe("string");
  });
});
