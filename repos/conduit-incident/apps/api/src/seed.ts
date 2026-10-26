import type { Db } from "./db";
import { createArticle, favorite } from "./services/articles";
import { addComment } from "./services/comments";
import { follow, register } from "./services/users";
import { findUserByUsername } from "./repositories/users";

/** Demo data for local development. Tests never call this; they build their own state. */
export function seed(db: Db): void {
  for (const username of ["ada", "grace", "linus"]) {
    register(db, { username, email: `${username}@example.com`, password: "password123" });
  }
  const id = (username: string) => findUserByUsername(db, username)!.id;

  const articles = [
    { author: "ada", title: "Notes on the Analytical Engine", tags: ["history", "computing"] },
    { author: "grace", title: "Why COBOL Still Runs the World", tags: ["computing", "languages"] },
    { author: "linus", title: "Talk Is Cheap, Show Me the Code", tags: ["opensource"] },
    { author: "grace", title: "A Ship in Port Is Safe", tags: ["leadership"] },
  ];
  for (const a of articles) {
    createArticle(db, id(a.author), {
      title: a.title,
      description: `${a.title}, briefly.`,
      body: `# ${a.title}\n\nDemo content.`,
      tagList: a.tags,
    });
  }

  follow(db, "grace", id("ada"));
  favorite(db, "why-cobol-still-runs-the-world", id("ada"));
  favorite(db, "why-cobol-still-runs-the-world", id("linus"));
  addComment(db, "notes-on-the-analytical-engine", id("grace"), { body: "Ahead of its time." });
}
