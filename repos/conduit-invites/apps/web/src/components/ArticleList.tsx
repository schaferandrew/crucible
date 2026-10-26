import type { ArticleListQuery, ArticlesResponse } from "@conduit/shared";
import { useEffect, useState } from "react";
import { ArticlePreview } from "./ArticlePreview";
import { Pagination } from "./Pagination";

export const PAGE_SIZE = 10;

interface Props {
  /** Loads one page; ArticleList owns paging. */
  load: (page: Pick<ArticleListQuery, "limit" | "offset">) => Promise<ArticlesResponse>;
}

export function ArticleList({ load }: Props) {
  const [page, setPage] = useState(0);
  const [data, setData] = useState<ArticlesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    load({ limit: PAGE_SIZE, offset: page * PAGE_SIZE }).then(
      (result) => !cancelled && setData(result),
      (err: Error) => !cancelled && setError(err.message),
    );
    return () => {
      cancelled = true;
    };
  }, [load, page]);

  if (error) return <p role="alert">Could not load articles: {error}</p>;
  if (!data) return <p>Loading articles…</p>;
  if (data.articles.length === 0) return <p>No articles are here… yet.</p>;
  return (
    <section>
      {data.articles.map((article) => (
        <ArticlePreview key={article.slug} article={article} />
      ))}
      <Pagination total={data.articlesCount} pageSize={PAGE_SIZE} page={page} onChange={setPage} />
    </section>
  );
}
