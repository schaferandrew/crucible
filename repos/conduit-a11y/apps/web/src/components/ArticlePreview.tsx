import type { Article } from "@conduit/shared";
import { Link } from "react-router-dom";
import { FavoriteButton } from "./FavoriteButton";

export function ArticlePreview({ article }: { article: Article }) {
  return (
    <article className="article-preview" data-testid="article-preview">
      <header>
        <Link to={`/profile/${article.author.username}`}>{article.author.username}</Link>
        <time dateTime={article.createdAt}>{new Date(article.createdAt).toDateString()}</time>
        <FavoriteButton article={article} />
      </header>
      <Link to={`/article/${article.slug}`}>
        <h2>{article.title}</h2>
        <p>{article.description}</p>
      </Link>
      <ul className="tag-list">
        {article.tagList.map((tag) => (
          <li key={tag}>{tag}</li>
        ))}
      </ul>
    </article>
  );
}
