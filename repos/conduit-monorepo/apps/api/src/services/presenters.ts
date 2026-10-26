import type { Article, Comment, Profile, User } from "@conduit/shared";
import type { ArticleRow, CommentRow, Db, UserRow } from "../db";
import { favoritesCount, isFavorited, tagsForArticle } from "../repositories/articles";
import { findUserById, isFollowing } from "../repositories/users";
import { signToken } from "../auth/tokens";

// Rows -> API JSON. `viewerId` is the signed-in user, if any; it decides `following` and `favorited`.

export function presentUser(user: UserRow): User {
  return { email: user.email, token: signToken(user.id), username: user.username, bio: user.bio, image: user.image };
}

export function presentProfile(db: Db, user: UserRow, viewerId?: number): Profile {
  return { username: user.username, bio: user.bio, image: user.image, following: isFollowing(db, viewerId, user.id) };
}

export function presentArticle(db: Db, article: ArticleRow, viewerId?: number): Article {
  return {
    slug: article.slug,
    title: article.title,
    description: article.description,
    body: article.body,
    tagList: tagsForArticle(db, article.id),
    createdAt: article.createdAt.toISOString(),
    updatedAt: article.updatedAt.toISOString(),
    favorited: isFavorited(db, viewerId, article.id),
    favoritesCount: favoritesCount(db, article.id),
    author: presentProfile(db, findUserById(db, article.authorId)!, viewerId),
  };
}

export function presentComment(db: Db, comment: CommentRow, viewerId?: number): Comment {
  return {
    id: comment.id,
    createdAt: comment.createdAt.toISOString(),
    updatedAt: comment.updatedAt.toISOString(),
    body: comment.body,
    author: presentProfile(db, findUserById(db, comment.authorId)!, viewerId),
  };
}
