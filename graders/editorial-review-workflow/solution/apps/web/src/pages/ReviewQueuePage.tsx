import type { Article } from "@conduit/shared";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";

/** Editors work through submitted articles, oldest first: approve, or send back with feedback. */
export function ReviewQueuePage() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [feedback, setFeedback] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.reviewQueue().then(
      (r) => setArticles(r.articles),
      (err) => setError(err instanceof ApiError && err.status === 403 ? "Only editors can review articles." : String(err)),
    );
  }, []);

  async function decide(slug: string, approve: boolean) {
    try {
      if (approve) await api.approve(slug);
      else await api.reject(slug, feedback[slug] ?? "");
      setArticles((current) => current.filter((a) => a.slug !== slug));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <div className="review-page">
      <h1>Review queue</h1>
      {error && <p role="alert">{error}</p>}
      {!error && articles.length === 0 && <p>Nothing waiting for review.</p>}
      <ul>
        {articles.map((a) => (
          <li key={a.slug}>
            <Link to={`/article/${a.slug}`}>{a.title}</Link> by {a.author.username}
            <textarea
              aria-label={`Feedback for ${a.title}`}
              value={feedback[a.slug] ?? ""}
              onChange={(e) => setFeedback({ ...feedback, [a.slug]: e.target.value })}
            />
            <button type="button" onClick={() => decide(a.slug, true)}>Approve</button>
            <button type="button" onClick={() => decide(a.slug, false)} disabled={!(feedback[a.slug] ?? "").trim()}>
              Send back
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
