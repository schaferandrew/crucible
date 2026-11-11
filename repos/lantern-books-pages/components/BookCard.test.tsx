import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import BookCard from "./BookCard";
import { getBook } from "../lib/books";

afterEach(cleanup);

describe("BookCard", () => {
  it("links to the book with its author and price", () => {
    const book = getBook("rivers-of-glass")!;
    render(<ul><BookCard book={book} /></ul>);
    expect(screen.getByRole("link", { name: "Rivers of Glass" }).getAttribute("href")).toBe("/books/rivers-of-glass");
    expect(screen.getByText(/by Ines Okafor/)).toBeTruthy();
    expect(screen.getByText("$12.99")).toBeTruthy();
  });
});
