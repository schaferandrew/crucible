import request from "supertest";
import { describe, expect, it } from "vitest";
import { createApp } from "../src/app";
import { createDb } from "../src/db";

describe("response cache", () => {
  it("serves repeated anonymous reads from the cache", async () => {
    const app = createApp(createDb(), { responseCacheTtlMs: 60_000 });
    const first = await request(app).get("/api/tags").expect(200);
    const second = await request(app).get("/api/tags").expect(200);
    expect(first.headers["x-cache"]).toBe("MISS");
    expect(second.headers["x-cache"]).toBe("HIT");
  });

  it("is off unless a TTL is given", async () => {
    const app = createApp(createDb());
    await request(app).get("/api/tags").expect(200);
    const second = await request(app).get("/api/tags").expect(200);
    expect(second.headers["x-cache"]).toBeUndefined();
  });
});
