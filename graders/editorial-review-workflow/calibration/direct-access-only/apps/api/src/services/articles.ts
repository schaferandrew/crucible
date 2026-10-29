import {
  type Article,
  type ArticleStatus,
  type ArticlesResponse,
  type CreateArticleInput,
  type UpdateArticleInput,
  slugify,
} from "@conduit/shared";
import type { ArticleRow, Db } from "../db";
import { forbidden, notFound, unprocessable } from "../errors";
import {
  type ArticleFilter,
  addFavorite,
  deleteArticleRow,
  findArticleBySlug,
  insertArticle,
  listArticles,
  removeFavorite,
  reviewQueue as inReview,
  setArticleTags,
  slugTaken,
  updateArticleRow,
} from "../repositories/articles";
import { findUserByUsername, followedIds } from "../repositories/users";
import type { Policy } from "./policy";
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

/** An article the viewer may see. Anyone else gets the same 404 as for an article that doesn't exist. */
export function requireVisible(db: Db, policy: Policy, slug: string, viewerId?: number): ArticleRow {
  const article = findArticleBySlug(db, slug);
  if (!article || !policy.canView(article, viewerId)) throw notFound("article");
  return article;
}

function requireAuthor(article: ArticleRow, viewerId: number): void {
  if (article.authorId !== viewerId) throw forbidden("this article");
}

function present(db: Db, policy: Policy, article: ArticleRow, viewerId?: number): Article {
  return presentArticle(db, article, viewerId, policy.seesFeedback(article, viewerId));
}

const EMPTY: ArticlesResponse = { articles: [], articlesCount: 0 };

/** GET /articles: published articles, filtered by tag, author username and favoriting username. */
export function listArticlesForQuery(
  db: Db,
  policy: Policy,
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
  return { articles: rows.map((a) => present(db, policy, a, viewerId)), articlesCount: count };
}

/** GET /articles/feed: published articles by authors the viewer follows. */
export function feed(db: Db, policy: Policy, viewerId: number, page: Page): ArticlesResponse {
  const filter: ArticleFilter = { authorIds: followedIds(db, viewerId) };
  const { rows, count } = listArticles(db, filter, page.limit, page.offset);
  return { articles: rows.map((a) => present(db, policy, a, viewerId)), articlesCount: count };
}

/** GET /user/articles: the viewer's own articles of every status, newest first. */
export function ownArticles(db: Db, policy: Policy, viewerId: number, status: ArticleStatus | undefined, page: Page): ArticlesResponse {
  const { rows, count } = listArticles(db, { authorId: viewerId, status }, page.limit, page.offset);
  return { articles: rows.map((a) => present(db, policy, a, viewerId)), articlesCount: count };
}

/** GET /articles/review-queue: what an editor has to review, the longest waiting first. */
export function reviewQueue(db: Db, policy: Policy, viewerId: number, page: Page): ArticlesResponse {
  if (!policy.isEditor(viewerId)) throw forbidden("the review queue");
  const rows = inReview(db).filter((a) => a.authorId !== viewerId);
  return {
    articles: rows.slice(page.offset, page.offset + page.limit).map((a) => present(db, policy, a, viewerId)),
    articlesCount: rows.length,
  };
}

export function getArticle(db: Db, policy: Policy, slug: string, viewerId?: number): Article {
  return present(db, policy, requireVisible(db, policy, slug, viewerId), viewerId);
}

export function createArticle(db: Db, policy: Policy, authorId: number, input: CreateArticleInput): Article {
  const article = insertArticle(db, {
    slug: uniqueSlug(db, input.title),
    title: input.title,
    description: input.description,
    body: input.body,
    authorId,
    status: input.status ?? "published",
    reviewComment: null,
    submittedAt: null,
  });
  setArticleTags(db, article.id, input.tagList);
  return present(db, policy, article, authorId);
}

/** Editing keeps the article's status: a renamed article in review stays in review. */
export function updateArticle(db: Db, policy: Policy, slug: string, viewerId: number, input: UpdateArticleInput): Article {
  const article = requireArticle(db, slug);
  requireAuthor(article, viewerId);
  const fields: Parameters<typeof updateArticleRow>[2] = { ...input };
  if (input.title !== undefined && input.title !== article.title) {
    fields.slug = uniqueSlug(db, input.title, article.id);
  }
  return present(db, policy, updateArticleRow(db, article.id, fields), viewerId);
}

export function deleteArticle(db: Db, policy: Policy, slug: string, viewerId: number): void {
  const article = requireArticle(db, slug);
  requireAuthor(article, viewerId);
  deleteArticleRow(db, article.id);
}

export function favorite(db: Db, policy: Policy, slug: string, viewerId: number): Article {
  const article = requireArticle(db, slug);
  addFavorite(db, viewerId, article.id);
  return present(db, policy, article, viewerId);
}

export function unfavorite(db: Db, policy: Policy, slug: string, viewerId: number): Article {
  const article = requireVisible(db, policy, slug, viewerId);
  removeFavorite(db, viewerId, article.id);
  return present(db, policy, article, viewerId);
}

// --- editorial review: draft -> in_review -> published, or back to draft with feedback ----------

function requireStatus(article: ArticleRow, status: ArticleStatus, action: string): void {
  if (article.status !== status) throw unprocessable("status", `can't ${action} an article that is ${article.status}`);
}

/** Editors review other people's work: no one approves or rejects their own. */
function requireReviewer(db: Db, policy: Policy, slug: string, viewerId: number): ArticleRow {
  if (!policy.isEditor(viewerId)) throw forbidden("this article's review");
  return requireArticle(db, slug);
}

export function submitArticle(db: Db, policy: Policy, slug: string, viewerId: number): Article {
  const article = requireArticle(db, slug);
  requireAuthor(article, viewerId);
  requireStatus(article, "draft", "submit");
  return present(db, policy, updateArticleRow(db, article.id, { status: "in_review", submittedAt: db.now() }), viewerId);
}

export function approveArticle(db: Db, policy: Policy, slug: string, viewerId: number): Article {
  const article = requireReviewer(db, policy, slug, viewerId);
  requireStatus(article, "in_review", "approve");
  return present(db, policy, updateArticleRow(db, article.id, { status: "published", submittedAt: null }), viewerId);
}

export function rejectArticle(db: Db, policy: Policy, slug: string, viewerId: number, comment: string): Article {
  const article = requireReviewer(db, policy, slug, viewerId);
  requireStatus(article, "in_review", "reject");
  const row = updateArticleRow(db, article.id, { status: "draft", reviewComment: comment, submittedAt: null });
  return present(db, policy, row, viewerId);
}
