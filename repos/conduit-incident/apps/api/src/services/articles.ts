import {
  type Article,
  type ArticlesResponse,
  type CreateArticleInput,
  type UpdateArticleInput,
  slugify,
} from "@conduit/shared";
import type { ArticleRow, Db } from "../db";
import { forbidden, notFound } from "../errors";
import {
  type ArticleFilter,
  addFavorite,
  deleteArticleRow,
  findArticleBySlug,
  insertArticle,
  listArticles,
  removeFavorite,
  setArticleTags,
  slugTaken,
  updateArticleRow,
} from "../repositories/articles";
import { findUserByUsername, followedIds } from "../repositories/users";
import { presentArticle } from "./presenters";

export interface Page {
  limit: number;
  offset: number;
}

function uniqueSlug(db: Db, title: string, exceptId?: number): string {
  const base = slugify(title);
  let slug = base;
  for (let n = 2; slugTaken(db, slug, exceptId); n++) slug = `${base}-${n}`;
  return slug;
}

function requireArticle(db: Db, slug: string): ArticleRow {
  const article = findArticleBySlug(db, slug);
  if (!article) throw notFound("article");
  return article;
}

function requireAuthor(article: ArticleRow, viewerId: number): void {
  if (article.authorId !== viewerId) throw forbidden("this article");
}

const EMPTY: ArticlesResponse = { articles: [], articlesCount: 0 };

/** GET /articles: filter by tag, author username and favoriting username. */
export function listArticlesForQuery(
  db: Db,
  query: { tag?: string; author?: string; favorited?: string },
  page: Page,
  viewerId?: number,
): ArticlesResponse {
  const filter: ArticleFilter = { tag: query.tag };
  if (query.author !== undefined) {
    const author = findUserByUsername(db, query.author);
    if (!author) return EMPTY;
    filter.authorId = author.id;
  }
  if (query.favorited !== undefined) {
    const fan = findUserByUsername(db, query.favorited);
    if (!fan) return EMPTY;
    filter.favoritedById = fan.id;
  }
  const { rows, count } = listArticles(db, filter, page.limit, page.offset);
  return { articles: rows.map((a) => presentArticle(db, a, viewerId)), articlesCount: count };
}

/** GET /articles/feed: articles by authors the viewer follows. */
export function feed(db: Db, viewerId: number, page: Page): ArticlesResponse {
  const { rows, count } = listArticles(db, { authorIds: followedIds(db, viewerId) }, page.limit, page.offset);
  return { articles: rows.map((a) => presentArticle(db, a, viewerId)), articlesCount: count };
}

export function getArticle(db: Db, slug: string, viewerId?: number): Article {
  return presentArticle(db, requireArticle(db, slug), viewerId);
}

export function createArticle(db: Db, authorId: number, input: CreateArticleInput): Article {
  const article = insertArticle(db, {
    slug: uniqueSlug(db, input.title),
    title: input.title,
    description: input.description,
    body: input.body,
    authorId,
  });
  setArticleTags(db, article.id, input.tagList);
  return presentArticle(db, article, authorId);
}

export function updateArticle(db: Db, slug: string, viewerId: number, input: UpdateArticleInput): Article {
  const article = requireArticle(db, slug);
  requireAuthor(article, viewerId);
  const fields: Parameters<typeof updateArticleRow>[2] = { ...input };
  if (input.title !== undefined && input.title !== article.title) {
    fields.slug = uniqueSlug(db, input.title, article.id);
  }
  return presentArticle(db, updateArticleRow(db, article.id, fields), viewerId);
}

export function deleteArticle(db: Db, slug: string, viewerId: number): void {
  const article = requireArticle(db, slug);
  requireAuthor(article, viewerId);
  deleteArticleRow(db, article.id);
}

export function favorite(db: Db, slug: string, viewerId: number): Article {
  const article = requireArticle(db, slug);
  addFavorite(db, viewerId, article.id);
  return presentArticle(db, article, viewerId);
}

export function unfavorite(db: Db, slug: string, viewerId: number): Article {
  const article = requireArticle(db, slug);
  removeFavorite(db, viewerId, article.id);
  return presentArticle(db, article, viewerId);
}
