import request from "supertest";
import { beforeEach, describe, expect, it } from "vitest";
import { createApp } from "../src/app";
import { createDb } from "../src/db";

let app: ReturnType<typeof createApp>;
let editor: string;

beforeEach(async () => {
  app = createApp(createDb());
  const res = await request(app).post("/api/users")
    .send({ user: { username: "grace", email: "grace@example.com", password: "password123" } }).expect(201);
  editor = res.body.user.token;
});

describe("signing up with an invited address", () => {
  it("claims the invited account without recording the terms", async () => {
    await request(app).post("/api/invites").set({ Authorization: `Token ${editor}` })
      .send({ invite: { email: "pending@example.com" } }).expect(201);
    const res = await request(app).post("/api/users")
      .send({ user: { username: "pending", email: "pending@example.com", password: "password123" } }).expect(201);
    expect(res.body.user.accountState).toBe("invited");
    expect(res.body.user.termsAcceptedAt).toBeNull();
    await request(app).post("/api/users/login")
      .send({ user: { email: "pending@example.com", password: "password123" } }).expect(200);
  });

  it("only works once", async () => {
    await request(app).post("/api/invites").set({ Authorization: `Token ${editor}` })
      .send({ invite: { email: "pending@example.com" } }).expect(201);
    const claim = (username: string) => request(app).post("/api/users")
      .send({ user: { username, email: "pending@example.com", password: "password123" } });
    await claim("pending").expect(201);
    await claim("again").expect(422);
  });
});
