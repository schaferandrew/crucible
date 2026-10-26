// The RealWorld API contract (realworld.how), modelled on the project's official API test
// collection. Other RealWorld frontends depend on these shapes and statuses: keep this green.
// Like the official suite, it checks the fields the spec requires; extra fields are allowed.
import request from "supertest";
import { beforeEach, describe, expect, it } from "vitest";
import { auth, createArticle, freshApp, registerUser } from "./helpers";

let ctx: ReturnType<typeof freshApp>;
beforeEach(() => {
  ctx = freshApp();
});

const isoDate = expect.stringMatching(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/);

describe("Auth", () => {
  it("registers, logs in and returns the current user", async () => {
    const reg = await request(ctx.app)
      .post("/api/users")
      .send({ user: { username: "jake", email: "jake@jake.jake", password: "jakejake1" } })
      .expect(201);
    expect(reg.body.user).toMatchObject({
      email: "jake@jake.jake",
      token: expect.any(String),
      username: "jake",
      bio: null,
      image: null,
    });

    const login = await request(ctx.app)
      .post("/api/users/login")
      .send({ user: { email: "jake@jake.jake", password: "jakejake1" } })
      .expect(200);
    const me = await request(ctx.app).get("/api/user").set(auth(login.body.user.token)).expect(200);
    expect(me.body.user.username).toBe("jake");
  });

  it("rejects duplicate usernames and emails with 422", async () => {
    await registerUser(ctx.app, "jake");
    const res = await request(ctx.app)
      .post("/api/users")
      .send({ user: { username: "jake", email: "jake@example.com", password: "password123" } })
      .expect(422);
    expect(res.body.errors.username).toContain("has already been taken");
    expect(res.body.errors.email).toContain("has already been taken");
  });

  it("validates registration fields", async () => {
    const res = await request(ctx.app)
      .post("/api/users")
      .send({ user: { username: "", email: "not-an-email", password: "short" } })
      .expect(422);
    expect(Object.keys(res.body.errors).sort()).toEqual(["email", "password", "username"]);
  });

  it("rejects a wrong password with 401", async () => {
    await registerUser(ctx.app, "jake");
    await request(ctx.app)
      .post("/api/users/login")
      .send({ user: { email: "jake@example.com", password: "wrong-password" } })
      .expect(401);
  });

  it("requires a token for the current user and rejects a bad one", async () => {
    await request(ctx.app).get("/api/user").expect(401);
    await request(ctx.app).get("/api/user").set(auth("not-a-jwt")).expect(401);
  });

  it("updates the current user", async () => {
    const { token } = await registerUser(ctx.app, "jake");
    const res = await request(ctx.app)
      .put("/api/user")
      .set(auth(token))
      .send({ user: { bio: "I work at statefarm", image: "https://example.com/jake.png" } })
      .expect(200);
    expect(res.body.user).toMatchObject({ bio: "I work at statefarm", image: "https://example.com/jake.png" });
  });
});

describe("Profiles", () => {
  it("gets, follows and unfollows a profile", async () => {
    const jake = await registerUser(ctx.app, "jake");
    await registerUser(ctx.app, "celeb");

    const anon = await request(ctx.app).get("/api/profiles/celeb").expect(200);
    expect(anon.body.profile).toMatchObject({ username: "celeb", bio: null, image: null, following: false });

    const followed = await request(ctx.app).post("/api/profiles/celeb/follow").set(auth(jake.token)).expect(200);
    expect(followed.body.profile.following).toBe(true);

    const seen = await request(ctx.app).get("/api/profiles/celeb").set(auth(jake.token)).expect(200);
    expect(seen.body.profile.following).toBe(true);

    const unfollowed = await request(ctx.app).delete("/api/profiles/celeb/follow").set(auth(jake.token)).expect(200);
    expect(unfollowed.body.profile.following).toBe(false);
  });

  it("returns 404 for an unknown profile", async () => {
    await request(ctx.app).get("/api/profiles/nobody").expect(404);
  });
});

describe("Articles", () => {
  it("creates an article with the full article shape", async () => {
    const { token } = await registerUser(ctx.app, "jake");
    const res = await request(ctx.app)
      .post("/api/articles")
      .set(auth(token))
      .send({ article: { title: "How to train your dragon", description: "Ever wonder how?", body: "Very carefully.", tagList: ["training", "dragons"] } })
      .expect(201);
    expect(res.body.article).toMatchObject({
      slug: "how-to-train-your-dragon",
      title: "How to train your dragon",
      description: "Ever wonder how?",
      body: "Very carefully.",
      tagList: ["dragons", "training"],
      createdAt: isoDate,
      updatedAt: isoDate,
      favorited: false,
      favoritesCount: 0,
      author: { username: "jake", bio: null, image: null, following: false },
    });
  });

  it("requires auth to create and validates fields", async () => {
    await request(ctx.app).post("/api/articles").send({ article: { title: "x", description: "y", body: "z" } }).expect(401);
    const { token } = await registerUser(ctx.app, "jake");
    const res = await request(ctx.app).post("/api/articles").set(auth(token)).send({ article: { title: "" } }).expect(422);
    expect(res.body.errors).toHaveProperty("title");
  });

  it("gives duplicate titles distinct slugs", async () => {
    const { token } = await registerUser(ctx.app, "jake");
    const first = await createArticle(ctx.app, token, "Same Title");
    const second = await createArticle(ctx.app, token, "Same Title");
    expect(first.slug).toBe("same-title");
    expect(second.slug).toBe("same-title-2");
  });

  it("lists articles newest first, with filters and paging", async () => {
    const jake = await registerUser(ctx.app, "jake");
    const jane = await registerUser(ctx.app, "jane");
    for (let i = 1; i <= 5; i++) {
      await createArticle(ctx.app, i % 2 ? jake.token : jane.token, `Article ${i}`, i <= 2 ? ["early"] : []);
      ctx.tick();
    }

    const all = await request(ctx.app).get("/api/articles").expect(200);
    expect(all.body.articlesCount).toBe(5);
    expect(all.body.articles.map((a: { title: string }) => a.title)).toEqual(
      ["Article 5", "Article 4", "Article 3", "Article 2", "Article 1"],
    );

    const byAuthor = await request(ctx.app).get("/api/articles?author=jane").expect(200);
    expect(byAuthor.body.articlesCount).toBe(2);

    const byTag = await request(ctx.app).get("/api/articles?tag=early").expect(200);
    expect(byTag.body.articles.map((a: { title: string }) => a.title)).toEqual(["Article 2", "Article 1"]);

    const page = await request(ctx.app).get("/api/articles?limit=2&offset=2").expect(200);
    expect(page.body.articlesCount).toBe(5);
    expect(page.body.articles.map((a: { title: string }) => a.title)).toEqual(["Article 3", "Article 2"]);

    await request(ctx.app).get("/api/articles?limit=-1").expect(422);
    const unknownAuthor = await request(ctx.app).get("/api/articles?author=nobody").expect(200);
    expect(unknownAuthor.body).toMatchObject({ articles: [], articlesCount: 0 });
  });

  it("builds a feed from followed authors only", async () => {
    const jake = await registerUser(ctx.app, "jake");
    const celeb = await registerUser(ctx.app, "celeb");
    const other = await registerUser(ctx.app, "other");
    await createArticle(ctx.app, celeb.token, "Celeb news");
    await createArticle(ctx.app, other.token, "Other news");
    await request(ctx.app).post("/api/profiles/celeb/follow").set(auth(jake.token)).expect(200);

    const feed = await request(ctx.app).get("/api/articles/feed").set(auth(jake.token)).expect(200);
    expect(feed.body.articlesCount).toBe(1);
    expect(feed.body.articles[0]).toMatchObject({ title: "Celeb news", author: { following: true } });
    await request(ctx.app).get("/api/articles/feed").expect(401);
  });

  it("gets, updates and deletes an article; only the author may change it", async () => {
    const jake = await registerUser(ctx.app, "jake");
    const jane = await registerUser(ctx.app, "jane");
    const { slug } = await createArticle(ctx.app, jake.token, "Original Title");

    await request(ctx.app).get(`/api/articles/${slug}`).expect(200);
    await request(ctx.app).put(`/api/articles/${slug}`).set(auth(jane.token)).send({ article: { body: "hijack" } }).expect(403);

    const updated = await request(ctx.app)
      .put(`/api/articles/${slug}`)
      .set(auth(jake.token))
      .send({ article: { title: "New Title" } })
      .expect(200);
    expect(updated.body.article.slug).toBe("new-title");
    await request(ctx.app).get("/api/articles/new-title").expect(200);

    await request(ctx.app).delete("/api/articles/new-title").set(auth(jane.token)).expect(403);
    await request(ctx.app).delete("/api/articles/new-title").set(auth(jake.token)).expect(204);
    await request(ctx.app).get("/api/articles/new-title").expect(404);
  });
});

describe("Favorites", () => {
  it("favorites and unfavorites, counting per user", async () => {
    const jake = await registerUser(ctx.app, "jake");
    const jane = await registerUser(ctx.app, "jane");
    const { slug } = await createArticle(ctx.app, jake.token, "Popular");

    const fav = await request(ctx.app).post(`/api/articles/${slug}/favorite`).set(auth(jane.token)).expect(200);
    expect(fav.body.article).toMatchObject({ favorited: true, favoritesCount: 1 });

    const asJake = await request(ctx.app).get(`/api/articles/${slug}`).set(auth(jake.token)).expect(200);
    expect(asJake.body.article).toMatchObject({ favorited: false, favoritesCount: 1 });

    const byFan = await request(ctx.app).get("/api/articles?favorited=jane").expect(200);
    expect(byFan.body.articlesCount).toBe(1);

    const unfav = await request(ctx.app).delete(`/api/articles/${slug}/favorite`).set(auth(jane.token)).expect(200);
    expect(unfav.body.article).toMatchObject({ favorited: false, favoritesCount: 0 });
  });
});

describe("Comments", () => {
  it("adds, lists and deletes comments; only the author may delete", async () => {
    const jake = await registerUser(ctx.app, "jake");
    const jane = await registerUser(ctx.app, "jane");
    const { slug } = await createArticle(ctx.app, jake.token, "Discuss");

    const added = await request(ctx.app)
      .post(`/api/articles/${slug}/comments`)
      .set(auth(jane.token))
      .send({ comment: { body: "Thank you so much!" } })
      .expect(201);
    expect(added.body.comment).toMatchObject({
      id: expect.any(Number),
      createdAt: isoDate,
      updatedAt: isoDate,
      body: "Thank you so much!",
      author: { username: "jane", bio: null, image: null, following: false },
    });

    const list = await request(ctx.app).get(`/api/articles/${slug}/comments`).expect(200);
    expect(list.body.comments).toHaveLength(1);

    const id = added.body.comment.id;
    await request(ctx.app).delete(`/api/articles/${slug}/comments/${id}`).set(auth(jake.token)).expect(403);
    await request(ctx.app).delete(`/api/articles/${slug}/comments/${id}`).set(auth(jane.token)).expect(204);
    const after = await request(ctx.app).get(`/api/articles/${slug}/comments`).expect(200);
    expect(after.body.comments).toEqual([]);
  });
});

describe("Tags", () => {
  it("lists tags in use, most used first", async () => {
    const { token } = await registerUser(ctx.app, "jake");
    await createArticle(ctx.app, token, "One", ["common", "rare"]);
    await createArticle(ctx.app, token, "Two", ["common"]);
    const res = await request(ctx.app).get("/api/tags").expect(200);
    expect(res.body.tags).toEqual(["common", "rare"]);
  });
});

describe("Errors", () => {
  it("returns 404 in the error envelope for unknown routes", async () => {
    const res = await request(ctx.app).get("/api/nope").expect(404);
    expect(res.body).toHaveProperty("errors");
  });

  it("returns 422 for malformed JSON", async () => {
    await request(ctx.app).post("/api/users").set("Content-Type", "application/json").send("{bad json").expect(422);
  });
});
