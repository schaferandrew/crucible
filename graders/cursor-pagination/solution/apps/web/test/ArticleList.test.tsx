import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ArticleList, PAGE_SIZE } from "../src/components/ArticleList";
import { makeArticle, page, renderWithProviders } from "./render";

describe("ArticleList", () => {
  it("renders a page of previews", async () => {
    const load = vi.fn().mockResolvedValue(page([makeArticle({ slug: "a", title: "First" }), makeArticle({ slug: "b", title: "Second" })]));
    renderWithProviders(<ArticleList load={load} />);
    expect(await screen.findByText("First")).toBeInTheDocument();
    expect(screen.getAllByTestId("article-preview")).toHaveLength(2);
    expect(load).toHaveBeenCalledWith({ limit: PAGE_SIZE });
  });

  it("shows an empty state", async () => {
    renderWithProviders(<ArticleList load={vi.fn().mockResolvedValue(page([]))} />);
    expect(await screen.findByText(/No articles are here/)).toBeInTheDocument();
  });

  it("loads the next page by cursor and keeps the loaded articles", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce(page([makeArticle({ slug: "a", title: "First" })], "cursor-2"))
      .mockResolvedValueOnce(page([makeArticle({ slug: "b", title: "Second" })], null));
    renderWithProviders(<ArticleList load={load} />);
    await userEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Second")).toBeInTheDocument();
    expect(screen.getByText("First")).toBeInTheDocument();
    expect(load).toHaveBeenLastCalledWith({ limit: PAGE_SIZE, cursor: "cursor-2" });
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("has no Load more button on the last page", async () => {
    renderWithProviders(<ArticleList load={vi.fn().mockResolvedValue(page([makeArticle()]))} />);
    await screen.findByText("An Article");
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("reports load errors", async () => {
    renderWithProviders(<ArticleList load={vi.fn().mockRejectedValue(new Error("boom"))} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });
});
