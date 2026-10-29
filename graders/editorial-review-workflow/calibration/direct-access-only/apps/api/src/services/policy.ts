import type { ArticleRow, Db } from "../db";
import { findUserById } from "../repositories/users";

// Who may see and review what. Editors are configured by username: createApp(db, { editors: ["ada"] }).

export interface Policy {
  isEditor(viewerId?: number): boolean;
  /** Published articles are public; drafts only their author sees; editors also see what's in review */
  canView(article: ArticleRow, viewerId?: number): boolean;
  /** Feedback is between the author and the editors */
  seesFeedback(article: ArticleRow, viewerId?: number): boolean;
}

export function createPolicy(db: Db, editors: string[] = []): Policy {
  const usernames = new Set(editors.map((e) => e.trim()).filter(Boolean));
  const isEditor = (viewerId?: number) =>
    viewerId !== undefined && usernames.has(findUserById(db, viewerId)?.username ?? "");
  return {
    isEditor,
    canView: (article, viewerId) =>
      article.status === "published" ||
      article.authorId === viewerId ||
      (article.status === "in_review" && isEditor(viewerId)),
    seesFeedback: (article, viewerId) => article.authorId === viewerId || isEditor(viewerId),
  };
}

