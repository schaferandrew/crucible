// @vitest-environment node
// Level 1 of CODE-16: the production build succeeds and /contact serves the form's HTML.
// Next can't prerender a Server Component that passes event handlers to elements, so the seeded
// form fails here before any interaction is possible. See form.grader.test.tsx for the rest.
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { createServer } from "node:net";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const root = path.resolve(__dirname, "../..");
const next = path.join(root, "node_modules", ".bin", "next");
const env = { ...process.env, NEXT_TELEMETRY_DISABLED: "1", NODE_ENV: "production" };

let build: ReturnType<typeof spawnSync>;
let server: ChildProcess | undefined;
let html = "";
let status = 0;

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const probe = createServer().listen(0, "127.0.0.1", () => {
      const { port } = probe.address() as { port: number };
      probe.close(() => resolve(port));
    }).on("error", reject);
  });
}

async function fetchPage(url: string, deadline: number) {
  for (;;) {
    try {
      const res = await fetch(url);
      return { status: res.status, html: await res.text() };
    } catch (err) {
      if (Date.now() > deadline) throw err;
      await new Promise((r) => setTimeout(r, 250));
    }
  }
}

beforeAll(async () => {
  build = spawnSync(next, ["build"], { cwd: root, env, encoding: "utf8", timeout: 240_000 });
  if (build.status !== 0) return;
  const port = await freePort();
  server = spawn(next, ["start", "-p", String(port), "-H", "127.0.0.1"], { cwd: root, env, stdio: "ignore" });
  ({ status, html } = await fetchPage(`http://127.0.0.1:${port}/contact`, Date.now() + 30_000));
}, 300_000);

afterAll(() => {
  server?.kill("SIGTERM");
});

describe("level 1: renders", () => {
  it("the production build succeeds", () => {
    const tail = `${build.stdout ?? ""}${build.stderr ?? ""}`.slice(-1500);
    expect(build.status, tail).toBe(0);
  });

  it("/contact serves the form, rendered on the server", () => {
    expect(status).toBe(200);
    for (const id of ["lead-form", "lead-name", "lead-email", "lead-company", "lead-message", "lead-submit"]) {
      expect(html, `#${id}`).toContain(`id="${id}"`);
    }
  });
});
