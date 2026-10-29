import type { Article, ArticleListQuery, ArticlesResponse } from "@conduit/shared";
import { useEffect, useRef, useState } from "react";
import { ArticlePreview } from "./ArticlePreview";
import { LoadMore } from "./LoadMore";

export const PAGE_SIZE = 10;

interface Props {
  /** Loads one page; ArticleList owns paging, by the cursor of the previous page. */
  load: (page: Pick<ArticleListQuery, "limit" | "cursor">) => Promise<ArticlesResponse>;
}

export function ArticleList({ load }: Props) {
  const [articles, setArticles] = useState<Article[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Only the latest load may update the list: a stale response is dropped
  const generation = useRef(0);

  useEffect(() => {
    const mine = ++generation.current;
    setArticles(null);
    setNextCursor(null);
    load({ limit: PAGE_SIZE }).then(
      (result) => {
        if (mine !== generation.current) return;
        setArticles(result.articles);
        setNextCursor(result.nextCursor);
      },
      (err: Error) => mine === generation.current && setError(err.message),
    );
    return () => {
      generation.current++;
    };
  }, [load]);

  async function loadMore() {
    if (!nextCursor || loadingMore) return;
    const mine = generation.current;
    setLoadingMore(true);
    try {
      const result = await load({ limit: PAGE_SIZE, cursor: nextCursor });
      if (mine !== generation.current) return;
      setArticles((current) => [...(current ?? []), ...result.articles]);
      setNextCursor(result.nextCursor);
    } catch (err) {
      if (mine === generation.current) setError((err as Error).message);
    } finally {
      setLoadingMore(false);
    }
  }

  if (error) return <p role="alert">Could not load articles: {error}</p>;
  if (!articles) return <p>Loading articles…</p>;
  if (articles.length === 0) return <p>No articles are here… yet.</p>;
  return (
    <section>
      {articles.map((article) => (
        <ArticlePreview key={article.slug} article={article} />
      ))}
      <LoadMore cursor={nextCursor} loading={loadingMore} onClick={loadMore} />
    </section>
  );
}
