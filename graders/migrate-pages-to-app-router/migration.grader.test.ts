// @vitest-environment node
// Hidden tests for migrate-pages-to-app-router. Never copied into the model's workspace: the grader
// copies this file into test/hidden/ of a grading copy (seeded repo + the model's pages, app,
// components, lib and styles) and runs it with the seeded vitest config.
//
// One production build and one `next start` serve every test. The tests compare what the old Pages
// Router app served (URLs, status codes, the content that matters, metadata) with what the migrated
// app serves, and read the source for the App Router rules a browser can't show (client boundaries).
// Every test needs an app/ directory, so every test fails on the seeded repo, whose pages build and
// serve the right content.
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { existsSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { createServer } from "node:net";
import path from "node:path";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

const root = path.resolve(__dirname, "../..");
const next = path.join(root, "node_modules", ".bin", "next");
const env = { ...process.env, NEXT_TELEMETRY_DISABLED: "1", NODE_ENV: "production" };

// The grading oracle can only overlay files, never delete them. A reference solution or fixture that
// has migrated away from pages/ ships pages/.crucible-removed in its place; a model that deletes
// pages/ simply has no such folder. Either way the copy under test has no old pages left.
const MARKER = path.join(root, "pages", ".crucible-removed");
if (existsSync(MARKER)) rmSync(path.join(root, "pages"), { recursive: true, force: true });

const BOOKS = {
  "a-short-history-of-lanterns": { title: "A Short History of Lanterns", author: "Peter Holm", price: "$21.99" },
  "harbor-towns-of-the-north": { title: "Harbor Towns of the North", author: "Gustav Reyes", price: "$24.99" },
  "quiet-engines": { title: "Quiet Engines", author: "Tobias Rahn", price: "$18.99" },
  "rivers-of-glass": { title: "Rivers of Glass", author: "Ines Okafor", price: "$12.99" },
  "the-mycelium-question": { title: "The Mycelium Question", author: "Lena Aaltonen", price: "$16.99" },
  "the-salt-cartographer": { title: "The Salt Cartographer", author: "Mara Venn", price: "$14.99" },
};
const SLUGS = Object.keys(BOOKS) as (keyof typeof BOOKS)[]; // already in title order
const GENRES = ["fiction", "science", "history"];
const PAGES = ["/", "/about", "/search", ...SLUGS.map((s) => `/books/${s}`), ...GENRES.map((g) => `/genres/${g}`)];

type Res = { status: number; html: string };
const got = new Map<string, Res>();
let build: ReturnType<typeof spawnSync>;
let server: ChildProcess | undefined;
let port = 0;
let views: number[] = [];

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const probe = createServer().listen(0, "127.0.0.1", () => {
      const { port } = probe.address() as { port: number };
      probe.close(() => resolve(port));
    }).on("error", reject);
  });
}

async function fetchUrl(url: string, deadline: number, init?: RequestInit): Promise<Res> {
  for (;;) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}${url}`, init);
      return { status: res.status, html: await res.text() };
    } catch (err) {
      if (Date.now() > deadline) throw err;
      await new Promise((r) => setTimeout(r, 250));
    }
  }
}

const viewCount = (html: string) => Number(/Viewed (\d+) times?/.exec(text(html))?.[1] ?? NaN);

beforeAll(async () => {
  build = spawnSync(next, ["build"], { cwd: root, env, encoding: "utf8", timeout: 240_000 });
  if (build.status !== 0) return;
  port = await freePort();
  server = spawn(next, ["start", "-p", String(port), "-H", "127.0.0.1"], { cwd: root, env, stdio: "ignore" });
  const deadline = Date.now() + 30_000;
  for (const url of [...PAGES, "/nope", "/books/no-such-book", "/genres/poetry", "/api/books",
    "/api/books?genre=science", "/api/books?genre=poetry"]) {
    got.set(url, await fetchUrl(url, deadline));
  }
  got.set("POST /api/books", await fetchUrl("/api/books", deadline, { method: "POST" }));
  // Three requests for one book, one after the other, for the "rendered on every request" test
  for (let i = 0; i < 3; i++) views.push(viewCount((await fetchUrl("/books/rivers-of-glass", deadline)).html));
}, 300_000);

afterAll(() => {
  server?.kill("SIGTERM");
});

const exists = (dir: string, names: string[]) =>
  names.some((n) => existsSync(path.join(root, dir, n)));
beforeEach(() => {
  const app = exists("app", ["layout.tsx", "layout.jsx", "layout.js", "layout.ts"]) &&
    exists("app", ["page.tsx", "page.jsx", "page.js", "page.ts"]);
  expect(app, "there's no app/layout and app/page: the app hasn't been migrated").toBe(true);
});

/** What the server answered for a URL (the build must have worked). */
function res(url: string): Res {
  const r = got.get(url);
  if (!r) throw new Error(`no response for ${url}: the build or the server failed`);
  return r;
}

/** Visible text of a page: scripts and tags dropped, React's comment markers removed. */
function text(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/g, "")
    .replace(/<!-- -->/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&#x27;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}
const body = (url: string) => text(res(url).html);
const titles = (html: string) => [...html.matchAll(/<title[^>]*>([^<]*)<\/title>/g)].map((m) => m[1]);
function description(html: string): string | undefined {
  for (const tag of html.match(/<meta\s[^>]*>/g) ?? []) {
    if (/name="description"/.test(tag)) return /content="([^"]*)"/.exec(tag)?.[1];
  }
}
function navLinks(html: string): { href: string; label: string; active: boolean }[] {
  const nav = /<nav[\s\S]*?<\/nav>/.exec(html)?.[0] ?? "";
  return [...nav.matchAll(/<a\s([^>]*)>([\s\S]*?)<\/a>/g)].map((m) => ({
    href: /href="([^"]*)"/.exec(m[1])?.[1] ?? "",
    label: text(m[2]),
    active: /aria-current="page"/.test(m[1]),
  }));
}
const activeHrefs = (url: string) => navLinks(res(url).html).filter((l) => l.active).map((l) => l.href);
const json = (url: string) => JSON.parse(res(url).html) as { books?: { slug: string; title: string }[]; error?: string };

// ---- Source scan --------------------------------------------------------------------------------
const SOURCE_DIRS = ["app", "components", "lib"];
function sources(dir: string): string[] {
  const full = path.join(root, dir);
  if (!existsSync(full)) return [];
  return readdirSync(full).flatMap((name) => {
    const p = path.join(full, name);
    if (statSync(p).isDirectory()) return sources(path.join(dir, name));
    return /\.(tsx?|jsx?)$/.test(name) && !/\.(test|spec)\./.test(name) ? [path.join(dir, name)] : [];
  });
}
const allSources = () => SOURCE_DIRS.flatMap(sources);
const read = (file: string) => readFileSync(path.join(root, file), "utf8");
const hasDirective = (src: string) => /^(?:\s|\/\/[^\n]*\n|\/\*[\s\S]*?\*\/)*["']use client["']/.test(src);
const HOOKS = /\buse(State|Effect|LayoutEffect|Reducer|Ref|Memo|Callback|Context|Transition|Id|Router|Params|Pathname|SearchParams|SelectedLayoutSegments?)\s*\(/;
const HANDLERS = /\bon(Click|Change|Submit|Input|KeyDown|Focus|Blur)\s*=/;

function importsOf(file: string, files: string[]): string[] {
  const out: string[] = [];
  for (const m of read(file).matchAll(/(?:from|import)\s*["']([^"']+)["']/g)) {
    const spec = m[1];
    const base = spec.startsWith("@/") ? spec.slice(2) : spec.startsWith(".") ? path.join(path.dirname(file), spec) : null;
    if (!base) continue;
    const hit = files.find((f) => f.replace(/\.(tsx?|jsx?)$/, "") === base || f.replace(/\/index\.(tsx?|jsx?)$/, "") === base);
    if (hit) out.push(hit);
  }
  return out;
}
/** A file is on the client when it says so, or when every file that imports it is. */
function clientFiles(files: string[]): Set<string> {
  const importers = new Map<string, string[]>(files.map((f) => [f, []]));
  for (const f of files) for (const i of importsOf(f, files)) importers.get(i)!.push(f);
  const memo = new Map<string, boolean>();
  const isClient = (f: string, seen: string[] = []): boolean => {
    if (memo.has(f)) return memo.get(f)!;
    if (hasDirective(read(f))) return true;
    const from = importers.get(f)!;
    if (seen.includes(f) || from.length === 0) return false;
    const result = from.every((i) => isClient(i, [...seen, f]));
    memo.set(f, result);
    return result;
  };
  return new Set(files.filter((f) => isClient(f)));
}

describe("migration: build and structure", () => {
  it("the production build succeeds", () => {
    const tail = `${build.stdout ?? ""}${build.stderr ?? ""}`.slice(-1500);
    expect(build.status, tail).toBe(0);
  });

  it("the pages/ directory is gone", () => {
    const left = ["pages", "src/pages"].filter((d) => existsSync(path.join(root, d)));
    expect(left, "the Pages Router folder is still there").toEqual([]);
  });

  it("every URL the old app served still answers 200", () => {
    for (const url of [...PAGES, "/api/books"]) expect(res(url).status, url).toBe(200);
  });
});

describe("migration: same content", () => {
  it("/ lists every book in title order with its author, price and link", () => {
    const { html } = res("/");
    const t = body("/");
    expect(t).toContain("Lantern Books");
    expect(t).toContain("6 titles, 5 in stock.");
    let at = 0;
    for (const slug of SLUGS) {
      const b = BOOKS[slug];
      const i = t.indexOf(b.title, at);
      expect(i, `${b.title} in title order`).toBeGreaterThanOrEqual(at);
      at = i + b.title.length;
      expect(html, slug).toContain(`href="/books/${slug}"`);
      expect(t).toContain(`${b.title} by ${b.author} ${b.price}`);
    }
  });

  it("/about keeps its text and opening hours", () => {
    const t = body("/about");
    expect(t).toContain("About Lantern Books");
    expect(t).toContain("run by two booksellers since 2009");
    expect(t).toContain("Monday to Friday: 9am to 6pm");
    expect(t).toContain("Saturday: 10am to 5pm");
    expect(t).toContain("Sunday: 11am to 3pm");
  });

  it("a book page shows the book, its genre link and its permalink", () => {
    const t = body("/books/quiet-engines");
    expect(res("/books/quiet-engines").status).toBe(200);
    expect(t).toContain("Quiet Engines");
    expect(t).toContain("by Tobias Rahn, 2021");
    expect(t).toContain("$18.99");
    expect(t).toContain("In stock");
    expect(t).toContain("Genre: Science");
    expect(res("/books/quiet-engines").html).toContain('href="/genres/science"');
    expect(t).toContain("How electric motors learned to disappear into everyday machines.");
    expect(t).toMatch(/Viewed \d+ times?/);
    expect(t).toContain("Permalink: /books/quiet-engines");
  });

  it("an out-of-stock book says so", () => {
    const t = body("/books/the-mycelium-question");
    expect(t).toContain("by Lena Aaltonen, 2023");
    expect(t).toContain("Out of stock");
    expect(t).not.toContain("In stock");
    expect(t).toContain("Permalink: /books/the-mycelium-question");
  });

  it("a genre page lists its shelf in title order", () => {
    const t = body("/genres/history");
    expect(t).toContain("History");
    expect(t).toContain("2 titles on this shelf.");
    expect(t.indexOf("A Short History of Lanterns")).toBeGreaterThan(-1);
    expect(t.indexOf("Harbor Towns of the North")).toBeGreaterThan(t.indexOf("A Short History of Lanterns"));
    expect(t).not.toContain("Quiet Engines");
    expect(res("/genres/history").html).toContain('href="/books/harbor-towns-of-the-north"');
  });

  it("another genre page lists only its own books", () => {
    const t = body("/genres/fiction");
    expect(t).toContain("2 titles on this shelf.");
    expect(t).toContain("Rivers of Glass by Ines Okafor $12.99");
    expect(t).toContain("The Salt Cartographer by Mara Venn $14.99");
    expect(t).not.toContain("Quiet Engines");
  });

  it("/search serves its heading in the HTML", () => {
    expect(body("/search")).toContain("Search the shop");
  });

  it("/api/books returns every book as JSON", () => {
    expect(json("/api/books").books?.map((b) => b.slug)).toEqual(SLUGS);
  });

  it("/api/books?genre= filters by genre", () => {
    expect(json("/api/books?genre=science").books?.map((b) => b.slug)).toEqual(["quiet-engines", "the-mycelium-question"]);
  });

  it("/api/books answers 400 for an unknown genre", () => {
    expect(res("/api/books?genre=poetry").status).toBe(400);
    expect(json("/api/books?genre=poetry").error).toBe("Unknown genre");
  });

  it("/api/books refuses anything but GET with 405", () => {
    expect(res("POST /api/books").status).toBe(405);
  });
});

describe("migration: shared layout", () => {
  it("every page sits in the layout: html lang, header, navigation and footer", () => {
    for (const url of ["/", "/about", "/search", "/books/quiet-engines", "/genres/fiction"]) {
      const { html } = res(url);
      expect(html, `${url} lang`).toMatch(/<html[^>]*\slang="en"/);
      expect(html, `${url} header`).toMatch(/<header[^>]*>[\s\S]*Lantern Books[\s\S]*<\/header>/);
      expect(navLinks(html).map((l) => [l.href, l.label]), `${url} nav`).toEqual([["/", "Books"], ["/search", "Search"], ["/about", "About"]]);
      expect(html, `${url} footer`).toMatch(/<footer[^>]*>[^<]*14 Quay Street/);
      expect(html, `${url} main`).toMatch(/<main[^>]*>[\s\S]*<h1[\s>]/);
    }
  });

  it("the global stylesheet is linked on every page", () => {
    for (const url of ["/", "/about", "/search", "/books/quiet-engines", "/genres/fiction"]) {
      expect(res(url).html, url).toMatch(/<link[^>]*rel="stylesheet"/);
    }
  });

  it("the nav marks Books as current on / and on book and genre pages", () => {
    for (const url of ["/", "/books/rivers-of-glass", "/genres/history"]) expect(activeHrefs(url), url).toEqual(["/"]);
  });

  it("the nav marks About as current on /about", () => {
    expect(activeHrefs("/about")).toEqual(["/about"]);
  });

  it("the nav marks Search as current on /search", () => {
    expect(activeHrefs("/search")).toEqual(["/search"]);
  });
});

describe("migration: not found", () => {
  it("an unknown URL answers 404 with the not-found page inside the layout", () => {
    const { status, html } = res("/nope");
    expect(status).toBe(404);
    const t = text(html);
    expect(t).toContain("Page not found");
    expect(t).toContain("We could not find that page.");
    expect(navLinks(html).length).toBe(3);
    expect(html).toContain('href="/"');
  });

  it("an unknown book slug answers 404 and serves no book", () => {
    const { status, html } = res("/books/no-such-book");
    expect(status).toBe(404);
    expect(html).not.toContain("<article");
    expect(text(html)).not.toContain("Permalink");
  });

  it("an unknown genre answers 404 with the not-found page, not an empty shelf", () => {
    const { status, html } = res("/genres/poetry");
    expect(status).toBe(404);
    expect(text(html)).toContain("Page not found");
    expect(text(html)).not.toContain("titles on this shelf");
  });
});

describe("migration: rendering semantics", () => {
  it("the book page is rendered on every request, so its view counter climbs", () => {
    expect(views.every(Number.isFinite), `view counts ${views}`).toBe(true);
    expect(views[1]).toBe(views[0] + 1);
    expect(views[2]).toBe(views[1] + 1);
  });

  it("the home, about and genre pages are still prerendered at build time", () => {
    const out = path.join(root, ".next", "server", "app");
    for (const file of ["index.html", "about.html", ...GENRES.map((g) => `genres/${g}.html`)]) {
      expect(existsSync(path.join(out, file)), file).toBe(true);
    }
  });
});

describe("migration: metadata", () => {
  const cases: [string, string, string][] = [
    ["/", "Lantern Books", "An independent bookshop with new and notable titles."],
    ["/about", "About | Lantern Books", "Who we are, where to find us and when we are open."],
    ["/genres/history", "History books | Lantern Books", "Browse our history shelf."],
    ["/search", "Search | Lantern Books", "Search the shop by title or author."],
  ];
  for (const [url, title, desc] of cases) {
    it(`${url} has its title and description, once`, () => {
      const { html } = res(url);
      expect(titles(html)).toEqual([title]);
      expect(description(html)).toBe(desc);
    });
  }

  it("book pages get their own title and description from the book", () => {
    for (const slug of ["quiet-engines", "the-mycelium-question"] as const) {
      const { html } = res(`/books/${slug}`);
      const b = BOOKS[slug];
      expect(titles(html), slug).toEqual([`${b.title} by ${b.author} | Lantern Books`]);
      expect(description(html), slug).toBeTruthy();
    }
    expect(description(res("/books/quiet-engines").html)).toBe("How electric motors learned to disappear into everyday machines.");
  });

  it("no Pages Router API is left in the source (next/head, next/router, getStaticProps...)", () => {
    const files = allSources();
    expect(files.length, "no source files under app/").toBeGreaterThan(0);
    const code = (f: string) => read(f).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    const legacy = files.filter((f) => /next\/head|next\/router|getStaticProps|getServerSideProps|getStaticPaths/.test(code(f)));
    expect(legacy).toEqual([]);
  });
});

describe("migration: client and server boundaries", () => {
  it("every file that uses hooks or event handlers is a client component or only used by one", () => {
    const files = allSources();
    expect(files.length, "no source files under app/").toBeGreaterThan(0);
    const client = clientFiles(files);
    const bad = files.filter((f) => (HOOKS.test(read(f)) || HANDLERS.test(read(f))) && !client.has(f));
    expect(bad, "hooks or handlers in a Server Component").toEqual([]);
  });

  it("no client component exports metadata", () => {
    const bad = allSources().filter((f) => hasDirective(read(f)) && /export\s+(const\s+metadata|(async\s+)?function\s+generateMetadata|const\s+generateMetadata)/.test(read(f)));
    expect(bad).toEqual([]);
  });

  it("the pages that load data stay Server Components", () => {
    const pages = ["app/page", "app/about/page", "app/books/[slug]/page", "app/genres/[genre]/page"];
    for (const p of pages) {
      const file = ["tsx", "jsx", "js", "ts"].map((e) => `${p}.${e}`).find((f) => existsSync(path.join(root, f)));
      expect(file, `${p} exists`).toBeTruthy();
      expect(hasDirective(read(file!)), `${file} is a Server Component`).toBe(false);
    }
  });

  it("the search page still fetches /api/books on mount, in a client component", () => {
    const files = allSources();
    const client = clientFiles(files);
    const hit = files.filter((f) => client.has(f) && /fetch\(\s*["'`]\/api\/books/.test(read(f)) && /useEffect\s*\(/.test(read(f)));
    expect(hit.length, "a client component with useEffect and fetch('/api/books')").toBeGreaterThan(0);
  });
});
