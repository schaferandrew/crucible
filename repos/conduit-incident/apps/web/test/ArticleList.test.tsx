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
    expect(load).toHaveBeenCalledWith({ limit: PAGE_SIZE, offset: 0 });
  });

  it("shows an empty state", async () => {
    renderWithProviders(<ArticleList load={vi.fn().mockResolvedValue(page([]))} />);
    expect(await screen.findByText(/No articles are here/)).toBeInTheDocument();
  });

  it("loads the next page by offset", async () => {
    const load = vi.fn().mockResolvedValue(page([makeArticle()], PAGE_SIZE * 3));
    renderWithProviders(<ArticleList load={load} />);
    await userEvent.click(await screen.findByRole("button", { name: "2" }));
    expect(load).toHaveBeenLastCalledWith({ limit: PAGE_SIZE, offset: PAGE_SIZE });
  });

  it("reports load errors", async () => {
    renderWithProviders(<ArticleList load={vi.fn().mockRejectedValue(new Error("boom"))} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });
});
