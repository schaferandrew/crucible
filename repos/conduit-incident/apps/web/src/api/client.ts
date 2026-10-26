import type {
  Article,
  ArticleListQuery,
  ArticlesResponse,
  Comment,
  Profile,
  User,
} from "@conduit/shared";

// The only module that talks to the API. Every function unwraps the RealWorld envelope.

export class ApiError extends Error {
  constructor(
    public status: number,
    public errors: Record<string, string[]>,
  ) {
    super(Object.entries(errors).map(([k, v]) => `${k} ${v.join(", ")}`).join("; ") || `HTTP ${status}`);
  }
}

let token: string | null = null;

export function setToken(value: string | null): void {
  token = value;
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Token ${token}`;
  const res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.errors ?? {});
  return data as T;
}

function queryString(query: object): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

export const api = {
  login: (email: string, password: string) =>
    call<{ user: User }>("POST", "/users/login", { user: { email, password } }).then((r) => r.user),
  register: (username: string, email: string, password: string) =>
    call<{ user: User }>("POST", "/users", { user: { username, email, password } }).then((r) => r.user),
  currentUser: () => call<{ user: User }>("GET", "/user").then((r) => r.user),

  profile: (username: string) => call<{ profile: Profile }>("GET", `/profiles/${encodeURIComponent(username)}`).then((r) => r.profile),
  follow: (username: string) => call<{ profile: Profile }>("POST", `/profiles/${encodeURIComponent(username)}/follow`).then((r) => r.profile),
  unfollow: (username: string) => call<{ profile: Profile }>("DELETE", `/profiles/${encodeURIComponent(username)}/follow`).then((r) => r.profile),

  articles: (query: ArticleListQuery = {}) => call<ArticlesResponse>("GET", `/articles${queryString(query)}`),
  feed: (query: Pick<ArticleListQuery, "limit" | "offset"> = {}) => call<ArticlesResponse>("GET", `/articles/feed${queryString(query)}`),
  article: (slug: string) => call<{ article: Article }>("GET", `/articles/${slug}`).then((r) => r.article),
  createArticle: (article: { title: string; description: string; body: string; tagList: string[] }) =>
    call<{ article: Article }>("POST", "/articles", { article }).then((r) => r.article),
  updateArticle: (slug: string, article: Partial<{ title: string; description: string; body: string }>) =>
    call<{ article: Article }>("PUT", `/articles/${slug}`, { article }).then((r) => r.article),
  deleteArticle: (slug: string) => call<void>("DELETE", `/articles/${slug}`),
  favorite: (slug: string) => call<{ article: Article }>("POST", `/articles/${slug}/favorite`).then((r) => r.article),
  unfavorite: (slug: string) => call<{ article: Article }>("DELETE", `/articles/${slug}/favorite`).then((r) => r.article),

  comments: (slug: string) => call<{ comments: Comment[] }>("GET", `/articles/${slug}/comments`).then((r) => r.comments),
  addComment: (slug: string, body: string) =>
    call<{ comment: Comment }>("POST", `/articles/${slug}/comments`, { comment: { body } }).then((r) => r.comment),
  deleteComment: (slug: string, id: number) => call<void>("DELETE", `/articles/${slug}/comments/${id}`),

  tags: () => call<{ tags: string[] }>("GET", "/tags").then((r) => r.tags),
};
