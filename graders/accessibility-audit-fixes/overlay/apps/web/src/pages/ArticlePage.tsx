import type { Article, Comment } from "@conduit/shared";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { FavoriteButton } from "../components/FavoriteButton";
import { ReadMore } from "../components/ReadMore";

export function ArticlePage() {
  const { slug = "" } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [article, setArticle] = useState<Article | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

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
            <button type="button" onClick={() => setConfirming(true)}>Delete Article</button>
          </>
        ) : (
          <FavoriteButton article={article} />
        )}
      </div>
      <ReadMore text={article.body} />
      <ConfirmDialog
        open={confirming}
        title="Delete this article?"
        message="This can't be undone. Comments and favorites are deleted too."
        onConfirm={remove}
        onCancel={() => setConfirming(false)}
      />

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
