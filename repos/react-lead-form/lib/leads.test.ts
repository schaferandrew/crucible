// @vitest-environment node
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { readLeads, saveLead } from "./leads";

let dir: string;
beforeEach(async () => {
  dir = await mkdtemp(path.join(tmpdir(), "leads-"));
  process.env.LEADS_FILE = path.join(dir, "leads.json");
});
afterEach(async () => {
  delete process.env.LEADS_FILE;
  await rm(dir, { recursive: true, force: true });
});

describe("lead store", () => {
  it("appends leads with increasing ids", async () => {
    await saveLead({ name: "Ann", email: "ann@example.com", company: "", message: "Two windows" });
    const second = await saveLead({ name: "Bo", email: "bo@example.com", company: "Bo's", message: "A door" });
    expect(second.id).toBe(2);
    expect((await readLeads()).map((l) => l.name)).toEqual(["Ann", "Bo"]);
  });
});
