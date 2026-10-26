import { useCallback, useEffect, useState } from "react";
import type { ArticleListQuery } from "@conduit/shared";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ArticleList } from "../components/ArticleList";

type Tab = { kind: "global" } | { kind: "feed" } | { kind: "tag"; tag: string };

export function HomePage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>(user ? { kind: "feed" } : { kind: "global" });
  const [tags, setTags] = useState<string[]>([]);

  useEffect(() => {
    api.tags().then(setTags, () => setTags([]));
  }, []);

  const load = useCallback(
    (page: Pick<ArticleListQuery, "limit" | "offset">) => {
      if (tab.kind === "feed") return api.feed(page);
      if (tab.kind === "tag") return api.articles({ ...page, tag: tab.tag });
      return api.articles(page);
    },
    [tab],
  );

  return (
    <div className="home-page">
      <nav className="feed-toggle">
        {user && (
          <button type="button" aria-pressed={tab.kind === "feed"} onClick={() => setTab({ kind: "feed" })}>
            Your Feed
          </button>
        )}
        <button type="button" aria-pressed={tab.kind === "global"} onClick={() => setTab({ kind: "global" })}>
          Global Feed
        </button>
        {tab.kind === "tag" && <span className="active-tag"># {tab.tag}</span>}
      </nav>
      {/* key resets ArticleList's page when the tab changes */}
      <ArticleList key={JSON.stringify(tab)} load={load} />
      <aside className="sidebar">
        <p>Popular Tags</p>
        {tags.map((tag) => (
          <button type="button" key={tag} className="tag-pill" onClick={() => setTab({ kind: "tag", tag })}>
            {tag}
          </button>
        ))}
      </aside>
    </div>
  );
}
