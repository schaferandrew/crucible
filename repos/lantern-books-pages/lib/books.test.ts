import { describe, expect, it } from "vitest";
import { booksByGenre, formatPrice, getAllBooks, getBook, getGenreSlugs, isGenre } from "./books";

describe("books", () => {
  it("lists every book sorted by title", () => {
    const titles = getAllBooks().map((b) => b.title);
    expect(titles).toHaveLength(6);
    expect(titles).toEqual([...titles].sort((a, b) => a.localeCompare(b)));
  });

  it("finds a book by slug and returns undefined for an unknown one", () => {
    expect(getBook("quiet-engines")?.author).toBe("Tobias Rahn");
    expect(getBook("no-such-book")).toBeUndefined();
  });

  it("filters by genre", () => {
    expect(booksByGenre("history").map((b) => b.slug)).toEqual([
      "harbor-towns-of-the-north",
      "a-short-history-of-lanterns",
    ].sort());
    expect(getGenreSlugs()).toEqual(["fiction", "science", "history"]);
    expect(isGenre("poetry")).toBe(false);
    expect(isGenre("toString")).toBe(false);
  });

  it("formats prices", () => {
    expect(formatPrice(1499)).toBe("$14.99");
    expect(formatPrice(1300)).toBe("$13.00");
  });
});
