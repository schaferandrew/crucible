// Hidden web tests for cursor-pagination (formerly CODE-12). Never copied into the model's workspace.
// They drive the real pages through fetch, so they hold for any component structure: the API is
// faked by URL, paged by whatever cursor the previous response handed out.
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../../src/App";
import { AuthProvider } from "../../src/auth/AuthContext";

const profile = { username: "jake", bio: null, image: null, following: false };
const article = (n: number) => ({
  slug: `story-${n}`, title: `Story ${n}`, description: `About ${n}`, body: "Body", tagList: [],
  createdAt: "2026-01-01T00:00:00.000Z", updatedAt: "2026-01-01T00:00:00.000Z",
  favorited: false, favoritesCount: 0, author: profile,
});
const comment = (n: number) => ({
  id: n, body: `Remark ${n}`, createdAt: "2026-01-01T00:00:00.000Z", updatedAt: "2026-01-01T00:00:00.000Z", author: profile,
});

type Pager = (cursor: string | null) => { items: unknown[]; next: string | null };

/** Three pages of two items; page k is served for cursor "cur-k" (page 1 for none). */
function pages(make: (n: number) => unknown): Pager {
  return (cursor) => {
    const k = cursor ? Number(cursor.replace("cur-", "")) : 1;
    return { items: [make(2 * k - 1), make(2 * k)], next: k < 3 ? `cur-${k + 1}` : null };
  };
}

let urls: URL[];
beforeEach(() => {
  urls = [];
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

function serve(opts: { articles?: Pager; comments?: Pager } = {}) {
  const json = (body: unknown) =>
    Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    urls.push(url);
    const cursor = url.searchParams.get("cursor");
    if (url.pathname === "/api/tags") return json({ tags: [] });
    if (url.pathname === "/api/user") return json({ user: { email: "j@x.com", token: "t", username: "jake", bio: null, image: null } });
    if (url.pathname.startsWith("/api/profiles/")) return json({ profile });
    if (url.pathname === "/api/articles/story-1") return json({ article: article(1) });
    if (url.pathname.endsWith("/comments")) {
      const page = (opts.comments ?? pages(comment))(cursor);
      return json({ comments: page.items, nextCursor: page.next });
    }
    if (url.pathname === "/api/articles" || url.pathname === "/api/articles/feed") {
      const page = (opts.articles ?? pages(article))(cursor);
      return json({ articles: page.items, articlesCount: 6, nextCursor: page.next });
    }
    return Promise.resolve(new Response("{}", { status: 404 }));
  }));
}

function open(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

const loadMore = () => screen.findByRole("button", { name: /load more/i });
const titles = () => screen.queryAllByRole("heading", { level: 2 }).map((h) => h.textContent);

describe("web: load more", () => {
  it("the home page loads more articles and keeps the loaded ones on screen", async () => {
    serve();
    open("/");
    await userEvent.click(await loadMore());
    await waitFor(() => expect(titles()).toEqual(["Story 1", "Story 2", "Story 3", "Story 4"]));
  });

  it("the home page asks for the next page with the cursor it was given, not an offset", async () => {
    serve();
    open("/");
    await userEvent.click(await loadMore());
    await waitFor(() => expect(titles()).toHaveLength(4));
    const second = urls.filter((u) => u.pathname === "/api/articles").find((u) => u.searchParams.get("cursor") === "cur-2");
    expect(second).toBeDefined();
    expect(second!.searchParams.has("offset")).toBe(false);
  });

  it("the Load more button is gone on the last page", async () => {
    serve();
    open("/");
    await userEvent.click(await loadMore());
    await waitFor(() => expect(titles()).toHaveLength(4));
    await userEvent.click(await loadMore());
    await waitFor(() => expect(titles()).toHaveLength(6));
    expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
  });

  it("there is no Load more button when everything fits on one page", async () => {
    // a Load more button anywhere would be a bug; the feature itself is probed by the cursor request
    serve({ articles: () => ({ items: [article(1), article(2)], next: null }) });
    open("/");
    await waitFor(() => expect(titles()).toEqual(["Story 1", "Story 2"]));
    expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
    // and a longer list does get one, so the test can't pass by having no button at all
    cleanup();
    serve();
    open("/");
    expect(await loadMore()).toBeInTheDocument();
  });

  it("numbered pagination is gone", async () => {
    serve();
    open("/");
    await loadMore();
    expect(screen.queryByRole("navigation", { name: /pagination/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "2" })).not.toBeInTheDocument();
  });

  it("the signed-in feed loads more the same way", async () => {
    localStorage.setItem("conduit.jwt", "t");
    serve();
    open("/");
    await userEvent.click(await screen.findByRole("button", { name: /your feed/i }));
    await waitFor(() => expect(urls.some((u) => u.pathname === "/api/articles/feed")).toBe(true));
    await userEvent.click(await loadMore());
    await waitFor(() => expect(titles()).toHaveLength(4));
    expect(urls.some((u) => u.pathname === "/api/articles/feed" && u.searchParams.get("cursor") === "cur-2")).toBe(true);
  });

  it("the profile's articles load more, keeping the author filter", async () => {
    serve();
    open("/profile/jake");
    await userEvent.click(await loadMore());
    await waitFor(() => expect(titles()).toHaveLength(4));
    const second = urls.find((u) => u.pathname === "/api/articles" && u.searchParams.get("cursor") === "cur-2");
    expect(second?.searchParams.get("author")).toBe("jake");
  });

  it("the profile's favorited tab loads more, keeping the favorited filter", async () => {
    serve();
    open("/profile/jake");
    await loadMore();
    await userEvent.click(screen.getByRole("button", { name: /favorited articles/i }));
    await waitFor(() => expect(urls.some((u) => u.searchParams.get("favorited") === "jake")).toBe(true));
    await userEvent.click(await loadMore());
    await waitFor(() => expect(titles()).toHaveLength(4));
    const second = urls.find((u) => u.searchParams.get("cursor") === "cur-2" && u.searchParams.get("favorited") === "jake");
    expect(second).toBeDefined();
  });

  it("comments on the article page load more and stay on screen", async () => {
    serve();
    open("/article/story-1");
    await screen.findByText("Remark 1");
    await userEvent.click(await loadMore());
    await screen.findByText("Remark 3");
    for (const n of [1, 2, 3, 4]) expect(screen.getByText(`Remark ${n}`)).toBeInTheDocument();
    const second = urls.find((u) => u.pathname.endsWith("/comments") && u.searchParams.get("cursor") === "cur-2");
    expect(second).toBeDefined();
  });

  it("the comments' Load more button is gone on the last page", async () => {
    serve();
    open("/article/story-1");
    await userEvent.click(await loadMore());
    await screen.findByText("Remark 3");
    await userEvent.click(await loadMore());
    await screen.findByText("Remark 6");
    expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
    expect(within(document.body).getAllByText(/^Remark \d$/)).toHaveLength(6);
  });
});
