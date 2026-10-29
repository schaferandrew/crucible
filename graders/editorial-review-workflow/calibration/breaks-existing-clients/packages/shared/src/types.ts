// JSON shapes of the RealWorld API (https://realworld-docs.netlify.app/specifications/backend/api-response-format/).
// Both apps import these, so changing a response shape surfaces everywhere it's used.

export interface User {
  email: string;
  token: string;
  username: string;
  bio: string | null;
  image: string | null;
}

export interface Profile {
  username: string;
  bio: string | null;
  image: string | null;
  following: boolean;
}

/** Where an article stands in editorial review. Only "published" articles are public. */
export type ArticleStatus = "draft" | "in_review" | "published";
export const ARTICLE_STATUSES: ArticleStatus[] = ["draft", "in_review", "published"];

export interface Article {
  slug: string;
  title: string;
  description: string;
  body: string;
  tagList: string[];
  createdAt: string;
  updatedAt: string;
  favorited: boolean;
  favoritesCount: number;
  author: Profile;
  status: ArticleStatus;
  /** The editor's feedback when the article was last sent back; null for anyone but its author and editors */
  reviewComment: string | null;
}

export interface Comment {
  id: number;
  createdAt: string;
  updatedAt: string;
  body: string;
  author: Profile;
}

export interface UserResponse {
  user: User;
}

export interface ProfileResponse {
  profile: Profile;
}

export interface ArticleResponse {
  article: Article;
}

export interface ArticlesResponse {
  articles: Article[];
  articlesCount: number;
}

export interface CommentResponse {
  comment: Comment;
}

export interface CommentsResponse {
  comments: Comment[];
}

export interface TagsResponse {
  tags: string[];
}

export interface ErrorResponse {
  errors: Record<string, string[]>;
}

export interface ArticleListQuery {
  tag?: string;
  author?: string;
  favorited?: string;
  limit?: number;
  offset?: number;
}

export const DEFAULT_PAGE_SIZE = 20;
export const MAX_PAGE_SIZE = 100;
