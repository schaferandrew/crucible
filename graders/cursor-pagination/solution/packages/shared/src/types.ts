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
  /** the total that matches the filters, not the size of this page */
  articlesCount: number;
  /** opaque cursor for the next page, or null on the last page */
  nextCursor: string | null;
}

export interface CommentResponse {
  comment: Comment;
}

export interface CommentsResponse {
  comments: Comment[];
  /** opaque cursor for the next page, or null on the last page (and when everything was returned) */
  nextCursor: string | null;
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
  /** offset paging; cannot be combined with cursor */
  offset?: number;
  /** a previous response's nextCursor */
  cursor?: string;
}

export interface CommentListQuery {
  limit?: number;
  cursor?: string;
}

export const DEFAULT_PAGE_SIZE = 20;
export const MAX_PAGE_SIZE = 100;
