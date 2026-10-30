// Hidden acceptance tests for invite-signup-loop (formerly CODE-14), API side. Never copied into the model's workspace.
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

const headers = (token: string) => ({ Authorization: `Token ${token}` });

async function invite(email: string) {
  const res = await request(app).post("/api/invites").set({ Authorization: `Token ${editor}` })
    .send({ invite: { email } }).expect(201);
  return res.body.invite.token as string;
}

const signUp = (username: string, email: string, password = "password123") =>
  request(app).post("/api/users").send({ user: { username, email, password } });

// Legal's requirements are the authority (docs/legal-contributor-terms.md): an account that can
// publish has accepted the terms and we can show when. Each test below needs the sign-up path for
// an invited address to work, which is what support reported for pending@example.com.
describe("invite sign-up: an invited address claims its account", () => {
  it("someone who signs up with an invited email ends up with their invited account", async () => {
    await invite("pending@example.com");
    const res = await signUp("pending", "pending@example.com");
    expect(res.status).toBe(201);
    expect(res.body.user.email).toBe("pending@example.com");
    expect(res.body.user.username).toBe("pending");
    expect(res.body.user.accountState).toBe("invited");
    await request(app).post("/api/users/login")
      .send({ user: { email: "pending@example.com", password: "password123" } }).expect(200);
  });

  it("an invited account can't be claimed twice", async () => {
    await invite("once@example.com");
    await signUp("once", "once@example.com").expect(201);
    await signUp("twice", "once@example.com", "password456").expect(422);
    await request(app).post("/api/users/login")
      .send({ user: { email: "once@example.com", password: "password123" } }).expect(200);
  });

  it("an invited sign-up gets the username it chose, and can't take one that is in use", async () => {
    await invite("pending@example.com");
    await signUp("grace", "pending@example.com").expect(422);
    const res = await signUp("pending", "pending@example.com");
    expect(res.status).toBe(201);
    expect(res.body.user.username).toBe("pending");
  });
});

describe("terms: recorded only when accepted", () => {
  it("signing up doesn't count as accepting the terms", async () => {
    await invite("pending@example.com");
    const res = await signUp("pending", "pending@example.com");
    expect(res.status).toBe(201);
    expect(res.body.user.termsAcceptedAt).toBeNull();
    const me = await request(app).get("/api/user").set(headers(res.body.user.token)).expect(200);
    expect(me.body.user.termsAcceptedAt).toBeNull();
  });

  it("the terms are recorded when they accept them, and the profile is optional", async () => {
    await invite("pending@example.com");
    const signed = await signUp("pending", "pending@example.com");
    expect(signed.status).toBe(201);
    const res = await request(app).post("/api/user/onboarding").set(headers(signed.body.user.token))
      .send({ onboarding: { acceptTerms: true } }).expect(200);
    expect(res.body.user.termsAcceptedAt).toBeTruthy();
    expect(Number.isNaN(Date.parse(res.body.user.termsAcceptedAt))).toBe(false);
    const me = await request(app).get("/api/user").set(headers(signed.body.user.token)).expect(200);
    expect(me.body.user.termsAcceptedAt).toBe(res.body.user.termsAcceptedAt);
    await request(app).post("/api/articles").set(headers(signed.body.user.token))
      .send({ article: { title: "First piece", description: "d", body: "b" } }).expect(201);
  });

  it("the terms can't be skipped when accepting", async () => {
    await invite("pending@example.com");
    const signed = await signUp("pending", "pending@example.com");
    expect(signed.status).toBe(201);
    await request(app).post("/api/user/onboarding").set(headers(signed.body.user.token))
      .send({ onboarding: { bio: "hi" } }).expect(422);
    const me = await request(app).get("/api/user").set(headers(signed.body.user.token)).expect(200);
    expect(me.body.user.termsAcceptedAt).toBeNull();
  });
});

describe("unchanged: accepting an invite and regular sign-ups", () => {
  it("accepting an invite records the terms and gives a working account, next to a claimed one", async () => {
    await invite("pending@example.com");
    expect((await signUp("pending", "pending@example.com")).status).toBe(201);
    const token = await invite("rosa@example.com");
    const res = await request(app).post(`/api/invites/${token}/accept`)
      .send({ invite: { username: "rosa", password: "password123", acceptTerms: true } }).expect(200);
    expect(res.body.user.termsAcceptedAt).toBeTruthy();
    expect(res.body.user.accountState).toBe("invited");
    const me = await request(app).get("/api/user").set(headers(res.body.user.token)).expect(200);
    expect(me.body.user.termsAcceptedAt).toBeTruthy();
    await request(app).post("/api/articles").set(headers(res.body.user.token))
      .send({ article: { title: "First piece", description: "d", body: "b" } }).expect(201);
  });

  it("regular sign-ups are unchanged, next to an invited one", async () => {
    await invite("pending@example.com");
    const claimed = await signUp("pending", "pending@example.com");
    expect(claimed.status).toBe(201);
    const regular = await signUp("newbie", "newbie@example.com");
    expect(regular.status).toBe(201);
    expect(regular.body.user).toMatchObject({
      username: "newbie", email: "newbie@example.com", accountState: "active",
      onboardingComplete: false, termsAcceptedAt: null,
    });
    const done = await request(app).post("/api/user/onboarding").set(headers(regular.body.user.token))
      .send({ onboarding: { bio: "Hello", acceptTerms: true } }).expect(200);
    expect(done.body.user).toMatchObject({ bio: "Hello", onboardingComplete: true });
    expect(done.body.user.termsAcceptedAt).toBeTruthy();
  });

  it("a real duplicate sign-up is still rejected, next to an invited one", async () => {
    await invite("pending@example.com");
    expect((await signUp("pending", "pending@example.com")).status).toBe(201);
    const email = await signUp("grace2", "grace@example.com");
    expect(email.status).toBe(422);
    expect(email.body.errors.email).toBeTruthy();
    const username = await signUp("grace", "other@example.com");
    expect(username.status).toBe(422);
    expect(username.body.errors.username).toBeTruthy();
  });
});
