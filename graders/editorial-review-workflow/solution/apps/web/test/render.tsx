import type { Article, ArticlesResponse } from "@conduit/shared";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../src/auth/AuthContext";

export function renderWithProviders(ui: ReactElement, route = "/") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>,
  );
}

export function makeArticle(overrides: Partial<Article> = {}): Article {
  return {
    slug: "an-article",
    title: "An Article",
    description: "About things",
    body: "Body",
    tagList: [],
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
    favorited: false,
    favoritesCount: 0,
    author: { username: "jake", bio: null, image: null, following: false },
    status: "published",
    reviewComment: null,
    ...overrides,
  };
}

export function page(articles: Article[], articlesCount = articles.length): ArticlesResponse {
  return { articles, articlesCount };
}
