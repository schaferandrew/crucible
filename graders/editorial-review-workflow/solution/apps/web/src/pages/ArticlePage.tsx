import type { Article, Comment } from "@conduit/shared";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { FavoriteButton } from "../components/FavoriteButton";

export function ArticlePage() {
  const { slug = "" } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [article, setArticle] = useState<Article | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.article(slug).then(setArticle, (err: Error) => setError(err.message));
    api.comments(slug).then(setComments, () => setComments([]));
  }, [slug]);

  async function postComment(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    const comment = await api.addComment(slug, draft);
    setComments((current) => [comment, ...current]);
    setDraft("");
  }

  async function submitForReview() {
    setArticle(await api.submit(slug));
  }

  async function remove() {
    await api.deleteArticle(slug);
    navigate("/");
  }

  if (error) return <p role="alert">{error}</p>;
  if (!article) return <p>Loading…</p>;
  const isAuthor = user?.username === article.author.username;

  return (
    <div className="article-page">
      <h1>{article.title}</h1>
      <div className="article-meta">
        <Link to={`/profile/${article.author.username}`}>{article.author.username}</Link>
        {isAuthor ? (
          <>
            <Link to={`/editor/${article.slug}`}>Edit Article</Link>
            <button type="button" onClick={remove}>Delete Article</button>
          </>
        ) : (
          <FavoriteButton article={article} />
        )}
      </div>
      {article.status !== "published" && (
        <p className="article-status">
          Status: {article.status === "draft" ? "Draft" : "In review"}
          {isAuthor && article.status === "draft" && (
            <button type="button" onClick={submitForReview}>Submit for review</button>
          )}
        </p>
      )}
      {article.reviewComment && article.status === "draft" && (
        <p className="review-comment">Sent back: {article.reviewComment}</p>
      )}
      <div className="article-body">{article.body}</div>

      <section className="comments">
        {user && (
          <form onSubmit={postComment}>
            <textarea aria-label="Write a comment" value={draft} onChange={(e) => setDraft(e.target.value)} />
            <button type="submit">Post Comment</button>
          </form>
        )}
        {comments.map((comment) => (
          <div key={comment.id} className="comment">
            <p>{comment.body}</p>
            <span>{comment.author.username}</span>
          </div>
        ))}
      </section>
    </div>
  );
}
