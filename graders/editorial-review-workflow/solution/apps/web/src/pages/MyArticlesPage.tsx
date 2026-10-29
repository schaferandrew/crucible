import type { Article, ArticleStatus } from "@conduit/shared";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";

const LABELS: Record<ArticleStatus, string> = { draft: "Draft", in_review: "In review", published: "Published" };

/** The signed-in author's articles of every status, with feedback and a way to submit drafts. */
export function MyArticlesPage() {
  const [status, setStatus] = useState<ArticleStatus | "">("");
  const [articles, setArticles] = useState<Article[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.myArticles(status || undefined).then((r) => setArticles(r.articles), (err: Error) => setError(err.message));
  }, [status]);

  async function submit(slug: string) {
    try {
      const updated = await api.submit(slug);
      setArticles((current) => current.map((a) => (a.slug === slug ? updated : a)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <div className="my-articles-page">
      <h1>My Articles</h1>
      <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value as ArticleStatus | "")}>
        <option value="">All</option>
        <option value="draft">Drafts</option>
        <option value="in_review">In review</option>
        <option value="published">Published</option>
      </select>
      {error && <p role="alert">{error}</p>}
      {articles.length === 0 && <p>No articles here yet.</p>}
      <ul>
        {articles.map((a) => (
          <li key={a.slug}>
            <Link to={`/article/${a.slug}`}>{a.title}</Link> <span className="status">{LABELS[a.status]}</span>
            {a.status === "draft" && a.reviewComment && <p className="review-comment">Sent back: {a.reviewComment}</p>}
            {a.status === "draft" && (
              <button type="button" onClick={() => submit(a.slug)}>Submit for review</button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
