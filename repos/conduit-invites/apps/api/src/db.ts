// In-memory store shaped like a relational schema. Repositories are the only code that touches it.

export interface UserRow {
  id: number;
  username: string;
  email: string;
  passwordHash: string;
  bio: string | null;
  image: string | null;
  accountState: "active" | "invited";
  onboardingComplete: boolean;
  termsAcceptedAt: Date | null;
}

export interface InviteRow {
  token: string;
  userId: number;
  invitedById: number;
  createdAt: Date;
  acceptedAt: Date | null;
}

export interface ArticleRow {
  id: number;
  slug: string;
  title: string;
  description: string;
  body: string;
  authorId: number;
  createdAt: Date;
  updatedAt: Date;
}

export interface CommentRow {
  id: number;
  articleId: number;
  authorId: number;
  body: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface TagRow {
  id: number;
  name: string;
}

export interface Db {
  users: Map<number, UserRow>;
  articles: Map<number, ArticleRow>;
  comments: Map<number, CommentRow>;
  tags: Map<number, TagRow>;
  invites: Map<string, InviteRow>;
  /** join tables */
  articleTags: Array<{ articleId: number; tagId: number }>;
  favorites: Array<{ userId: number; articleId: number }>;
  follows: Array<{ followerId: number; followingId: number }>;
  /** next primary key per table */
  sequences: Record<"users" | "articles" | "comments" | "tags", number>;
  /** injectable clock so tests can control timestamps */
  now: () => Date;
}

export function createDb(now: () => Date = () => new Date()): Db {
  return {
    users: new Map(),
    articles: new Map(),
    comments: new Map(),
    tags: new Map(),
    invites: new Map(),
    articleTags: [],
    favorites: [],
    follows: [],
    sequences: { users: 1, articles: 1, comments: 1, tags: 1 },
    now,
  };
}

export function nextId(db: Db, table: keyof Db["sequences"]): number {
  return db.sequences[table]++;
}
