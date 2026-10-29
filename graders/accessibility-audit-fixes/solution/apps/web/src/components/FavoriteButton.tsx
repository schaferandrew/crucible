import type { Article } from "@conduit/shared";
import { useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";

/** Toggles a favorite. Shows the server's answer, so the count is always the real one. */
export function FavoriteButton({ article }: { article: Article }) {
  const { user } = useAuth();
  const [state, setState] = useState({ favorited: article.favorited, count: article.favoritesCount });
  const [busy, setBusy] = useState(false);

  async function toggle() {
    if (!user || busy) return;
    setBusy(true);
    try {
      const updated = state.favorited ? await api.unfavorite(article.slug) : await api.favorite(article.slug);
      setState({ favorited: updated.favorited, count: updated.favoritesCount });
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      className={state.favorited ? "favorite active" : "favorite"}
      aria-label={`Favorite (${state.count})`}
      aria-pressed={state.favorited}
      disabled={!user || busy}
      onClick={toggle}
    >
      <span className="icon icon-heart" aria-hidden="true" />
      <span className="count">{state.count}</span>
    </button>
  );
}
