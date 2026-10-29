// @vitest-environment node
// Hidden tests for nextjs-server-data-boundary (formerly CODE-3). Never copied into the model's
// workspace: the grader copies this file into test/hidden/ of a grading copy (seeded repo + the
// model's app/ and lib/) and runs it with the seeded vitest config.
//
// One production build and one `next start` serve every test. The seeded page uses useState in a
// Server Component, so the build fails and every test here fails with it.
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
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

/** Every file under .next/static: the JavaScript the browser downloads. */
function clientFiles(dir = path.join(root, ".next", "static")): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    return statSync(full).isDirectory() ? clientFiles(full) : [full];
  });
}

function clientCode(): string {
  return clientFiles().filter((f) => f.endsWith(".js")).map((f) => readFileSync(f, "utf8")).join("\n");
}

/** The page's text, with React's comment markers between text pieces removed. */
const visible = () => html.replace(/<!-- -->/g, "");

function builtOk() {
  const tail = `${build.stdout ?? ""}${build.stderr ?? ""}`.slice(-1500);
  expect(build.status, tail).toBe(0);
}

beforeAll(async () => {
  build = spawnSync(next, ["build"], { cwd: root, env, encoding: "utf8", timeout: 240_000 });
  if (build.status !== 0) return;
  const port = await freePort();
  server = spawn(next, ["start", "-p", String(port), "-H", "127.0.0.1"], { cwd: root, env, stdio: "ignore" });
  ({ status, html } = await fetchPage(`http://127.0.0.1:${port}/`, Date.now() + 30_000));
}, 300_000);

afterAll(() => {
  server?.kill("SIGTERM");
});

describe("renders", () => {
  it("the production build succeeds", () => {
    builtOk();
  });

  it("/ serves acct_1's name and plan in the server-rendered HTML", () => {
    builtOk();
    expect(status).toBe(200);
    expect(visible()).toContain("Name: Alice");
    expect(visible()).toContain("Plan: Pro");
  });

  it("/ serves the data, not a loading placeholder", () => {
    builtOk();
    expect(visible()).not.toMatch(/loading/i);
  });

  it("the page keeps its markup: a main with the Account heading, then the name and plan", () => {
    builtOk();
    expect(visible()).toMatch(/<main[^>]*>\s*<h1[^>]*>Account<\/h1>\s*<p[^>]*>Name: Alice<\/p>\s*<p[^>]*>Plan: Pro<\/p>/);
  });
});

describe("server data boundary", () => {
  it("app/page.tsx stays a Server Component", () => {
    builtOk();
    const page = readFileSync(path.join(root, "app", "page.tsx"), "utf8");
    expect(page).not.toMatch(/^\s*(['"])use client\1/m);
  });

  it("the browser does not fetch the account itself", () => {
    builtOk();
    expect(clientFiles().length, "no client files were built").toBeGreaterThan(0);
    expect(clientCode()).not.toContain("/api/account");
  });
});

describe("client bundle", () => {
  it("the account data never reaches a client bundle", () => {
    builtOk();
    expect(clientFiles().length, "no client files were built").toBeGreaterThan(0);
    const code = clientCode();
    for (const marker of ["Bob", "Basic", "acct_2"]) {
      expect(code, `"${marker}" is in the JavaScript sent to the browser`).not.toContain(marker);
    }
  });

  it("other accounts' records are not sent to the browser in the page payload", () => {
    builtOk();
    expect(html).not.toContain("Bob");
    expect(html).not.toContain("Basic");
    expect(html).not.toContain("acct_2");
  });
});
