// Hidden acceptance tests for cursor-pagination (formerly CODE-12). Never copied into the model's workspace:
// the grader copies this file to apps/api/test/hidden/ of a grading copy (the seeded repo plus the model's
// source folders) and runs it from apps/api. Every test weighs the same.
// Every test starts by asking for a cursor page (beforeEach), so each one fails on the seeded repo.
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

async function comment(token: string, slug: string, body: string) {
  const res = await request(app).post(`/api/articles/${slug}/comments`).set(as(token)).send({ comment: { body } }).expect(201);
  if (!frozen) time += 1000;
  return String(res.body.comment.id);
}

const del = (token: string, slug: string) => request(app).delete(`/api/articles/${slug}`).set(as(token)).expect(204);

/** Walk a list with limit=3 (or `size`), running `between` after each page that has a successor. */
async function pageThrough(path: string, token?: string, between?: (n: number) => Promise<void>, size = 3) {
  const seen: string[] = [];
  let cursor: string | null | undefined;
  for (let n = 0; n < 50; n++) {
    const sep = path.includes("?") ? "&" : "?";
    const url = `${path}${sep}limit=${size}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
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

const cursorFrom = async (path: string, token?: string) =>
  (await request(app).get(path).set(token ? as(token) : {}).expect(200)).body.nextCursor as string;
const enc = encodeURIComponent;

let alice: string, bob: string;
beforeEach(async () => {
  time = Date.parse("2026-02-01T00:00:00Z");
  frozen = false;
  app = createApp(createDb(() => new Date(time)));
  alice = await user("alice");
  bob = await user("bob");
  // The feature must exist: a list response carries nextCursor (null when everything fits on the page)
  const probe = await request(app).get("/api/articles?limit=1").expect(200);
  expect(probe.body).toHaveProperty("nextCursor");
});

const seeds = async (who: string, n: number, prefix: string, tags: string[] = []) => {
  const slugs: string[] = [];
  for (let i = 0; i < n; i++) slugs.push(await post(who, `${prefix} ${i}`, tags));
  return slugs;
};

describe("cursor paging", () => {
  it("walks every article once, newest first, ending with nextCursor null", async () => {
    const slugs = await seeds(alice, 10, "A");
    expect(await pageThrough("/api/articles")).toEqual([...slugs].reverse());
  });

  it("ends with a null nextCursor when the last page is exactly full", async () => {
    await seeds(alice, 6, "Full");
    const first = await request(app).get("/api/articles?limit=3").expect(200);
    expect(typeof first.body.nextCursor).toBe("string");
    const second = await request(app).get(`/api/articles?limit=3&cursor=${enc(first.body.nextCursor)}`).expect(200);
    expect(second.body.articles).toHaveLength(3);
    expect(second.body.nextCursor).toBeNull();
  });

  it("is total even when createdAt ties", async () => {
    frozen = true;
    const slugs = await seeds(alice, 8, "Tie");
    const seen = await pageThrough("/api/articles");
    expect(new Set(seen).size).toBe(8);
    expect([...seen].sort()).toEqual([...slugs].sort());
  });

  it("never skips or repeats when articles are created between pages", async () => {
    const original = await seeds(alice, 9, "Base");
    const seen = await pageThrough("/api/articles", undefined, async (n) => {
      await post(bob, `Interloper ${n}`); // newer than everything read so far
    });
    expect(new Set(seen).size).toBe(seen.length);
    expect(seen.filter((s) => !s.startsWith("interloper"))).toEqual([...original].reverse());
  });

  it("never skips or repeats when an article already read is deleted between pages", async () => {
    const original = await seeds(alice, 9, "Gone");
    const seen = await pageThrough("/api/articles", undefined, async (n) => {
      if (n === 0) await del(alice, original[6]); // the last article of page 1, the one the cursor points at
    });
    expect(seen).toEqual([...original].reverse());
  });

  it("never skips or repeats when articles not yet read are deleted between pages", async () => {
    const original = await seeds(alice, 9, "Ahead");
    const seen = await pageThrough("/api/articles", undefined, async (n) => {
      if (n === 0) {
        await del(alice, original[3]);
        await del(alice, original[0]);
      }
    });
    expect(seen).toEqual([...original].reverse().filter((s) => s !== original[3] && s !== original[0]));
  });

  it("never skips or repeats with creates and deletes between every page", async () => {
    const original = await seeds(alice, 12, "Churn");
    const seen = await pageThrough("/api/articles", undefined, async (n) => {
      await post(bob, `Churn late ${n}`);
      // two articles of the page just read disappear, one of them the article the cursor points at
      await del(alice, original[11 - 3 * n]);
      await del(alice, original[9 - 3 * n]);
    });
    expect(new Set(seen).size).toBe(seen.length);
    expect(seen.filter((s) => !s.startsWith("churn-late"))).toEqual([...original].reverse());
  });

  it("never skips or repeats when an article is favorited between pages", async () => {
    const original = await seeds(alice, 9, "Fav");
    const seen = await pageThrough("/api/articles", bob, async () => {
      await request(app).post(`/api/articles/${original[0]}/favorite`).set(as(bob)).expect(200);
      await request(app).post(`/api/articles/${original[7]}/favorite`).set(as(bob)).expect(200);
    });
    expect(seen).toEqual([...original].reverse());
  });

  it("is stable when the page size changes between requests", async () => {
    const slugs = await seeds(alice, 7, "Size");
    const first = await request(app).get("/api/articles?limit=2").expect(200);
    const rest = await request(app).get(`/api/articles?limit=5&cursor=${enc(first.body.nextCursor)}`).expect(200);
    expect([...first.body.articles, ...rest.body.articles].map((a: { slug: string }) => a.slug)).toEqual([...slugs].reverse());
  });

  it("pages a tag filter", async () => {
    const tagged = await seeds(alice, 5, "Tagged", ["t"]);
    await seeds(bob, 3, "Other");
    expect(await pageThrough("/api/articles?tag=t")).toEqual([...tagged].reverse());
  });

  it("pages an author filter", async () => {
    await seeds(alice, 3, "Alice");
    const bobs = await seeds(bob, 4, "Bob");
    expect(await pageThrough("/api/articles?author=bob")).toEqual([...bobs].reverse());
  });

  it("pages the favorited filter", async () => {
    const slugs = await seeds(alice, 8, "Liked");
    for (const s of [slugs[0], slugs[2], slugs[3], slugs[5], slugs[7]]) {
      await request(app).post(`/api/articles/${s}/favorite`).set(as(bob)).expect(200);
    }
    expect(await pageThrough("/api/articles?favorited=bob")).toEqual([slugs[7], slugs[5], slugs[3], slugs[2], slugs[0]]);
  });

  it("pages the feed", async () => {
    await seeds(alice, 2, "Ignored");
    const bobs = await seeds(bob, 5, "Followed");
    const reader = await user("reader");
    await request(app).post("/api/profiles/bob/follow").set(as(reader)).expect(200);
    expect(await pageThrough("/api/articles/feed", reader)).toEqual([...bobs].reverse());
  });

  it("keeps the feed stable while the followed author publishes and deletes", async () => {
    const bobs = await seeds(bob, 8, "Feed");
    const reader = await user("reader");
    await request(app).post("/api/profiles/bob/follow").set(as(reader)).expect(200);
    const seen = await pageThrough("/api/articles/feed", reader, async (n) => {
      await post(bob, `Feed late ${n}`);
      if (n === 0) await del(bob, bobs[5]);
    });
    expect(new Set(seen).size).toBe(seen.length);
    expect(seen.filter((s) => !s.startsWith("feed-late"))).toEqual([...bobs].reverse());
  });

  it("keeps articlesCount as the filtered total on every page", async () => {
    await seeds(alice, 7, "C");
    await seeds(bob, 2, "D", ["d"]);
    const first = await request(app).get("/api/articles?limit=3").expect(200);
    expect(first.body.articlesCount).toBe(9);
    const second = await request(app).get(`/api/articles?limit=3&cursor=${enc(first.body.nextCursor)}`).expect(200);
    expect(second.body.articlesCount).toBe(9);
    const tagged = await request(app).get("/api/articles?tag=d&limit=1").expect(200);
    expect(tagged.body.articlesCount).toBe(2);
    expect(typeof tagged.body.nextCursor).toBe("string");
  });

  it("shows the viewer's favorited flag on a cursor page", async () => {
    const slugs = await seeds(alice, 5, "Flag");
    await request(app).post(`/api/articles/${slugs[1]}/favorite`).set(as(bob)).expect(200);
    const first = await request(app).get("/api/articles?limit=2").set(as(bob)).expect(200);
    const second = await request(app).get(`/api/articles?limit=2&cursor=${enc(first.body.nextCursor)}`).set(as(bob)).expect(200);
    const fav = second.body.articles.find((a: { slug: string }) => a.slug === slugs[1]);
    expect(fav).toMatchObject({ favorited: true, favoritesCount: 1 });
  });
});

describe("cursor paging: comments", () => {
  it("pages comments newest first, once each, ending with nextCursor null", async () => {
    const slug = await post(alice, "Chatty");
    const ids: string[] = [];
    for (let i = 0; i < 8; i++) ids.push(await comment(bob, slug, `c${i}`));
    expect(await pageThrough(`/api/articles/${slug}/comments`)).toEqual([...ids].reverse());
  });

  it("never skips or repeats when comments are added between pages", async () => {
    const slug = await post(alice, "Busy");
    const ids: string[] = [];
    for (let i = 0; i < 8; i++) ids.push(await comment(bob, slug, `c${i}`));
    const seen = await pageThrough(`/api/articles/${slug}/comments`, undefined, async (n) => {
      await comment(alice, slug, `late ${n}`);
    });
    const late = new Set(seen.filter((id) => !ids.includes(id)));
    expect(late.size).toBe(0); // newer than the walk: not part of it
    expect(seen).toEqual([...ids].reverse());
  });

  it("never skips or repeats when comments are deleted between pages", async () => {
    const slug = await post(alice, "Pruned");
    const ids: string[] = [];
    for (let i = 0; i < 9; i++) ids.push(await comment(bob, slug, `c${i}`));
    const seen = await pageThrough(`/api/articles/${slug}/comments`, undefined, async (n) => {
      if (n === 0) {
        await request(app).delete(`/api/articles/${slug}/comments/${ids[6]}`).set(as(bob)).expect(204); // the cursor's own comment
        await request(app).delete(`/api/articles/${slug}/comments/${ids[2]}`).set(as(bob)).expect(204);
      }
    });
    expect(seen).toEqual([...ids].reverse().filter((id) => id !== ids[2]));
  });

  it("is total even when comments share a createdAt", async () => {
    const slug = await post(alice, "Tied");
    frozen = true;
    const ids: string[] = [];
    for (let i = 0; i < 7; i++) ids.push(await comment(bob, slug, `c${i}`));
    const seen = await pageThrough(`/api/articles/${slug}/comments`);
    expect([...seen].sort()).toEqual([...ids].sort());
  });

  it("returns nextCursor as a string with a limit smaller than the comment count", async () => {
    const slug = await post(alice, "Few");
    for (let i = 0; i < 4; i++) await comment(bob, slug, `c${i}`);
    const res = await request(app).get(`/api/articles/${slug}/comments?limit=2`).expect(200);
    expect(res.body.comments).toHaveLength(2);
    expect(typeof res.body.nextCursor).toBe("string");
  });
});

describe("validation", () => {
  it("rejects a malformed cursor with the usual error envelope", async () => {
    await seeds(alice, 3, "V");
    const bad = await request(app).get("/api/articles?limit=2&cursor=not-a-cursor").expect(422);
    expect(bad.body.errors.cursor).toEqual(expect.arrayContaining([expect.any(String)]));
    await request(app).get(`/api/articles?limit=2&cursor=${enc("{}")}`).expect(422);
    await request(app).get("/api/articles?limit=2&cursor=!!!").expect(422);
  });

  it("rejects a cursor with its end altered", async () => {
    await seeds(alice, 5, "T");
    const cursor = await cursorFrom("/api/articles?limit=2");
    const flipped = cursor.slice(0, -2) + (cursor.endsWith("A") ? "BB" : "AA");
    await request(app).get(`/api/articles?limit=2&cursor=${enc(flipped)}`).expect(422);
  });

  it("rejects a cursor with its middle altered", async () => {
    await seeds(alice, 5, "M");
    const cursor = await cursorFrom("/api/articles?limit=2");
    const at = Math.floor(cursor.length / 3);
    const swapped = cursor[at] === "Q" ? "R" : "Q";
    await request(app).get(`/api/articles?limit=2&cursor=${enc(cursor.slice(0, at) + swapped + cursor.slice(at + 1))}`).expect(422);
  });

  it("rejects a cursor whose position was edited", async () => {
    await seeds(alice, 5, "P");
    const cursor = await cursorFrom("/api/articles?limit=2");
    const [head, ...rest] = cursor.split(".");
    let forged: string;
    try { // if the cursor wraps readable JSON, move the position it holds
      const data = JSON.parse(Buffer.from(head, "base64url").toString("utf8"));
      for (const k of Object.keys(data)) if (typeof data[k] === "number") data[k] = data[k] + 1;
      forged = [Buffer.from(JSON.stringify(data)).toString("base64url"), ...rest].join(".");
    } catch {
      forged = [...head].reverse().join("") + (rest.length ? "." + rest.join(".") : "");
    }
    await request(app).get(`/api/articles?limit=2&cursor=${enc(forged)}`).expect(422);
  });

  it("rejects a truncated cursor", async () => {
    await seeds(alice, 5, "Tr");
    const cursor = await cursorFrom("/api/articles?limit=2");
    await request(app).get(`/api/articles?limit=2&cursor=${enc(cursor.slice(0, Math.floor(cursor.length / 2)))}`).expect(422);
  });

  it("rejects a cursor made for a filter when it is used without one", async () => {
    await seeds(alice, 5, "NoF", ["x"]);
    const cursor = await cursorFrom("/api/articles?tag=x&limit=2");
    await request(app).get(`/api/articles?limit=2&cursor=${enc(cursor)}`).expect(422);
  });

  it("rejects a cursor used with a different tag", async () => {
    await seeds(alice, 5, "Tag", ["x"]);
    const cursor = await cursorFrom("/api/articles?tag=x&limit=2");
    await request(app).get(`/api/articles?tag=y&limit=2&cursor=${enc(cursor)}`).expect(422);
  });

  it("rejects an unfiltered cursor used with a filter", async () => {
    await seeds(alice, 5, "Wide", ["x"]);
    const cursor = await cursorFrom("/api/articles?limit=2");
    await request(app).get(`/api/articles?tag=x&limit=2&cursor=${enc(cursor)}`).expect(422);
    await request(app).get(`/api/articles?author=alice&limit=2&cursor=${enc(cursor)}`).expect(422);
    await request(app).get(`/api/articles?favorited=alice&limit=2&cursor=${enc(cursor)}`).expect(422);
  });

  it("rejects a cursor used with a different author", async () => {
    await seeds(alice, 5, "Au");
    await seeds(bob, 5, "Bu");
    const cursor = await cursorFrom("/api/articles?author=alice&limit=2");
    await request(app).get(`/api/articles?author=bob&limit=2&cursor=${enc(cursor)}`).expect(422);
  });

  it("rejects a list cursor on the feed, and a feed cursor on the list", async () => {
    await seeds(bob, 5, "Fd");
    const reader = await user("reader");
    await request(app).post("/api/profiles/bob/follow").set(as(reader)).expect(200);
    const listCursor = await cursorFrom("/api/articles?limit=2");
    const feedCursor = await cursorFrom("/api/articles/feed?limit=2", reader);
    await request(app).get(`/api/articles/feed?limit=2&cursor=${enc(listCursor)}`).set(as(reader)).expect(422);
    await request(app).get(`/api/articles?limit=2&cursor=${enc(feedCursor)}`).expect(422);
  });

  it("rejects an article cursor on comments, and a comment cursor on articles", async () => {
    const slug = await post(alice, "Mix");
    for (let i = 0; i < 4; i++) await comment(bob, slug, `c${i}`);
    await seeds(alice, 4, "Mx");
    const articleCursor = await cursorFrom("/api/articles?limit=2");
    const commentCursor = await cursorFrom(`/api/articles/${slug}/comments?limit=2`);
    await request(app).get(`/api/articles/${slug}/comments?limit=2&cursor=${enc(articleCursor)}`).expect(422);
    await request(app).get(`/api/articles?limit=2&cursor=${enc(commentCursor)}`).expect(422);
  });

  it("rejects cursor together with offset", async () => {
    await seeds(alice, 4, "O");
    const cursor = await cursorFrom("/api/articles?limit=2");
    const res = await request(app).get(`/api/articles?limit=2&offset=2&cursor=${enc(cursor)}`).expect(422);
    expect(res.body).toHaveProperty("errors");
  });

  it("rejects cursor together with offset=0, and on the feed", async () => {
    await seeds(bob, 4, "O0");
    const reader = await user("reader");
    await request(app).post("/api/profiles/bob/follow").set(as(reader)).expect(200);
    const cursor = await cursorFrom("/api/articles?limit=2");
    await request(app).get(`/api/articles?limit=2&offset=0&cursor=${enc(cursor)}`).expect(422);
    const feedCursor = await cursorFrom("/api/articles/feed?limit=2", reader);
    await request(app).get(`/api/articles/feed?limit=2&offset=1&cursor=${enc(feedCursor)}`).set(as(reader)).expect(422);
  });

  it("still requires sign-in for the feed when a cursor is sent", async () => {
    await request(app).get("/api/articles/feed?limit=2&cursor=abc").expect(401);
  });
});

describe("backward compatibility", () => {
  it("offset paging is unchanged", async () => {
    await seeds(alice, 5, "Off");
    const res = await request(app).get("/api/articles?limit=2&offset=2").expect(200);
    expect(res.body.articles.map((a: { title: string }) => a.title)).toEqual(["Off 2", "Off 1"]);
    expect(res.body.articlesCount).toBe(5);
  });

  it("offset paging works with filters and the feed", async () => {
    await seeds(alice, 4, "Fa", ["t"]);
    const bobs = await seeds(bob, 4, "Fb");
    const tagged = await request(app).get("/api/articles?tag=t&limit=2&offset=1").expect(200);
    expect(tagged.body.articles.map((a: { title: string }) => a.title)).toEqual(["Fa 2", "Fa 1"]);
    expect(tagged.body.articlesCount).toBe(4);
    const reader = await user("reader");
    await request(app).post("/api/profiles/bob/follow").set(as(reader)).expect(200);
    const feed = await request(app).get("/api/articles/feed?limit=2&offset=2").set(as(reader)).expect(200);
    expect(feed.body.articles.map((a: { slug: string }) => a.slug)).toEqual([bobs[1], bobs[0]]);
    expect(feed.body.articlesCount).toBe(4);
  });

  it("offset past the end returns an empty page with the total", async () => {
    await seeds(alice, 3, "End");
    const res = await request(app).get("/api/articles?limit=2&offset=10").expect(200);
    expect(res.body.articles).toEqual([]);
    expect(res.body.articlesCount).toBe(3);
  });

  it("a request without limit, offset or cursor still returns the newest articles first", async () => {
    const slugs = await seeds(alice, 4, "Plain");
    const res = await request(app).get("/api/articles").expect(200);
    expect(res.body.articles.map((a: { slug: string }) => a.slug)).toEqual([...slugs].reverse());
    expect(res.body.articlesCount).toBe(4);
  });

  it("a bad limit or offset is still a 422 in the old envelope", async () => {
    const limit = await request(app).get("/api/articles?limit=-1").expect(422);
    expect(limit.body.errors).toHaveProperty("limit");
    const offset = await request(app).get("/api/articles?offset=abc").expect(422);
    expect(offset.body.errors).toHaveProperty("offset");
  });

  it("an offset client can still walk the whole list, a cursor client in between changes nothing", async () => {
    const slugs = await seeds(alice, 7, "Mixed");
    await cursorFrom("/api/articles?limit=2");
    const seen: string[] = [];
    for (let offset = 0; offset < 7; offset += 3) {
      const res = await request(app).get(`/api/articles?limit=3&offset=${offset}`).expect(200);
      seen.push(...res.body.articles.map((a: { slug: string }) => a.slug));
    }
    expect(seen).toEqual([...slugs].reverse());
  });

  it("unpaged comments return everything, newest first", async () => {
    const slug = await post(alice, "Chatty");
    const ids: string[] = [];
    for (let i = 0; i < 25; i++) ids.push(await comment(bob, slug, `c${i}`));
    const all = await request(app).get(`/api/articles/${slug}/comments`).expect(200);
    expect(all.body.comments.map((c: { id: number }) => String(c.id))).toEqual([...ids].reverse());
  });

  it("a comments limit alone returns the newest page", async () => {
    const slug = await post(alice, "Limited");
    const ids: string[] = [];
    for (let i = 0; i < 6; i++) ids.push(await comment(bob, slug, `c${i}`));
    const res = await request(app).get(`/api/articles/${slug}/comments?limit=2`).expect(200);
    expect(res.body.comments.map((c: { id: number }) => String(c.id))).toEqual([ids[5], ids[4]]);
  });

  it("comments keep their shape", async () => {
    const slug = await post(alice, "Shape");
    await comment(bob, slug, "hello");
    const res = await request(app).get(`/api/articles/${slug}/comments?limit=5`).expect(200);
    expect(res.body.comments[0]).toMatchObject({ body: "hello", author: { username: "bob" } });
    expect(res.body.comments[0]).toHaveProperty("createdAt");
  });
});
