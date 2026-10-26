// JSON shapes of the RealWorld API (https://realworld-docs.netlify.app/specifications/backend/api-response-format/).
// Both apps import these, so changing a response shape surfaces everywhere it's used.

/** "invited": created by an editor's invite, before the person has signed in. */
export type AccountState = "active" | "invited";

export interface User {
  email: string;
  token: string;
  username: string;
  bio: string | null;
  image: string | null;
  accountState: AccountState;
  /** Profile setup finished on the welcome screen. Defaults to false for every new account. */
  onboardingComplete: boolean;
  /** When the contributor terms were accepted (ISO 8601), or null. */
  termsAcceptedAt: string | null;
}

export interface Invite {
  token: string;
  email: string;
  invitedBy: string;
  acceptedAt: string | null;
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
