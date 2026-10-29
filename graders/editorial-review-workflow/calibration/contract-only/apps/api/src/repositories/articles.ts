import type { ArticleStatus } from "@conduit/shared";
import { type ArticleRow, type Db, nextId } from "../db";

export function findArticleBySlug(db: Db, slug: string): ArticleRow | undefined {
  for (const article of db.articles.values()) if (article.slug === slug) return article;
  return undefined;
}

export function slugTaken(db: Db, slug: string, exceptId?: number): boolean {
  const found = findArticleBySlug(db, slug);
  return found !== undefined && found.id !== exceptId;
}

export function insertArticle(db: Db, fields: Omit<ArticleRow, "id" | "createdAt" | "updatedAt">): ArticleRow {
  const now = db.now();
  const row: ArticleRow = { id: nextId(db, "articles"), ...fields, createdAt: now, updatedAt: now };
  db.articles.set(row.id, row);
  return row;
}

export function updateArticleRow(db: Db, id: number, fields: Partial<Pick<ArticleRow, "slug" | "title" | "description" | "body" | "status" | "reviewComment" | "submittedAt">>): ArticleRow {
  const row = { ...db.articles.get(id)!, ...fields, updatedAt: db.now() };
  db.articles.set(id, row);
  return row;
}

export function deleteArticleRow(db: Db, id: number): void {
  db.articles.delete(id);
  db.articleTags = db.articleTags.filter((t) => t.articleId !== id);
  db.favorites = db.favorites.filter((f) => f.articleId !== id);
  for (const [commentId, comment] of db.comments) if (comment.articleId === id) db.comments.delete(commentId);
}

export interface ArticleFilter {
  tag?: string;
  authorId?: number;
  favoritedById?: number;
  authorIds?: Set<number>;
  status?: ArticleStatus;
}

/** Matching articles, newest first. Returns the page and the total count before paging. */
export function listArticles(db: Db, filter: ArticleFilter, limit: number, offset: number): { rows: ArticleRow[]; count: number } {
  let rows = [...db.articles.values()];
  if (filter.status !== undefined) rows = rows.filter((a) => a.status === filter.status);
  if (filter.tag !== undefined) {
    const tagId = findTagId(db, filter.tag);
    const ids = new Set(db.articleTags.filter((t) => t.tagId === tagId).map((t) => t.articleId));
    rows = rows.filter((a) => ids.has(a.id));
  }
  if (filter.authorId !== undefined) rows = rows.filter((a) => a.authorId === filter.authorId);
  if (filter.authorIds !== undefined) rows = rows.filter((a) => filter.authorIds!.has(a.authorId));
  if (filter.favoritedById !== undefined) {
    const ids = new Set(db.favorites.filter((f) => f.userId === filter.favoritedById).map((f) => f.articleId));
    rows = rows.filter((a) => ids.has(a.id));
  }
  rows.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime() || b.id - a.id);
  return { rows: rows.slice(offset, offset + limit), count: rows.length };
}

/** Articles in review, the longest waiting first. */
export function reviewQueue(db: Db): ArticleRow[] {
  return [...db.articles.values()]
    .filter((a) => a.status === "in_review")
    .sort((a, b) => a.submittedAt!.getTime() - b.submittedAt!.getTime() || a.id - b.id);
}

// --- tags ----------------------------------------------------------------

function findTagId(db: Db, name: string): number | undefined {
  for (const tag of db.tags.values()) if (tag.name === name) return tag.id;
  return undefined;
}

export function setArticleTags(db: Db, articleId: number, names: string[]): void {
  db.articleTags = db.articleTags.filter((t) => t.articleId !== articleId);
  for (const name of new Set(names)) {
    let tagId = findTagId(db, name);
    if (tagId === undefined) {
      tagId = nextId(db, "tags");
      db.tags.set(tagId, { id: tagId, name });
    }
    db.articleTags.push({ articleId, tagId });
  }
}

export function tagsForArticle(db: Db, articleId: number): string[] {
  return db.articleTags
    .filter((t) => t.articleId === articleId)
    .map((t) => db.tags.get(t.tagId)!.name)
    .sort();
}

/** Tags in use on published articles, most used first. */
export function popularTags(db: Db, limit = 20): string[] {
  const counts = new Map<number, number>();
  for (const { articleId, tagId } of db.articleTags) {
    counts.set(tagId, (counts.get(tagId) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || db.tags.get(a[0])!.name.localeCompare(db.tags.get(b[0])!.name))
    .slice(0, limit)
    .map(([id]) => db.tags.get(id)!.name);
}

// --- favorites -----------------------------------------------------------

export function isFavorited(db: Db, userId: number | undefined, articleId: number): boolean {
  if (userId === undefined) return false;
  return db.favorites.some((f) => f.userId === userId && f.articleId === articleId);
}

export function favoritesCount(db: Db, articleId: number): number {
  return db.favorites.filter((f) => f.articleId === articleId).length;
}

export function addFavorite(db: Db, userId: number, articleId: number): void {
  if (!isFavorited(db, userId, articleId)) db.favorites.push({ userId, articleId });
}

export function removeFavorite(db: Db, userId: number, articleId: number): void {
  db.favorites = db.favorites.filter((f) => !(f.userId === userId && f.articleId === articleId));
}
