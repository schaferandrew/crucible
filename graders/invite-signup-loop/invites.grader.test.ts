// Hidden acceptance tests for C14 (redirect loop), API side. Never copied into the model's workspace.
// The judge copies this file to apps/api/test/hidden/ in a scratch copy and runs:
//   npx vitest run test/hidden    (from apps/api)
import request from "supertest";
import { beforeEach, describe, expect, it } from "vitest";
import { createApp } from "../../src/app";
import { createDb } from "../../src/db";

let app: ReturnType<typeof createApp>;
let editor: string;

beforeEach(async () => {
  app = createApp(createDb());
  const res = await request(app).post("/api/users")
    .send({ user: { username: "grace", email: "grace@example.com", password: "password123" } }).expect(201);
  editor = res.body.user.token;
});

async function invite(email: string) {
  const res = await request(app).post("/api/invites").set({ Authorization: `Token ${editor}` })
    .send({ invite: { email } }).expect(201);
  return res.body.invite.token as string;
}

describe("invites", () => {
  it("accepting an invite records the terms and gives a working account", async () => {
    const token = await invite("rosa@example.com");
    const res = await request(app).post(`/api/invites/${token}/accept`)
      .send({ invite: { username: "rosa", password: "password123", acceptTerms: true } }).expect(200);
    expect(res.body.user.termsAcceptedAt).toBeTruthy();
    const me = await request(app).get("/api/user").set({ Authorization: `Token ${res.body.user.token}` }).expect(200);
    expect(me.body.user.termsAcceptedAt).toBeTruthy();
    await request(app).post("/api/articles").set({ Authorization: `Token ${res.body.user.token}` })
      .send({ article: { title: "First piece", description: "d", body: "b" } }).expect(201);
  });

  it("someone who signs up with an invited email ends up with their invited account", async () => {
    await invite("pending@example.com");
    const res = await request(app).post("/api/users")
      .send({ user: { username: "pending", email: "pending@example.com", password: "password123" } });
    expect(res.status).toBe(201);
    expect(res.body.user.email).toBe("pending@example.com");
    expect(res.body.user.accountState).toBe("invited");
    await request(app).post("/api/users/login")
      .send({ user: { email: "pending@example.com", password: "password123" } }).expect(200);
  });

  it("a real duplicate sign-up is still rejected", async () => {
    await request(app).post("/api/users")
      .send({ user: { username: "grace2", email: "grace@example.com", password: "password123" } }).expect(422);
  });

  it("an invited account can't be claimed twice", async () => {
    await invite("once@example.com");
    await request(app).post("/api/users").send({ user: { username: "once", email: "once@example.com", password: "password123" } }).expect(201);
    await request(app).post("/api/users").send({ user: { username: "twice", email: "once@example.com", password: "password456" } }).expect(422);
  });
});
