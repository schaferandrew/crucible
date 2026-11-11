"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import BookCard from "../../components/BookCard";
import type { Book } from "../../lib/books";

export default function SearchClient() {
  const initial = useSearchParams().get("q") ?? "";
  const [books, setBooks] = useState<Book[] | null>(null);
  const [query, setQuery] = useState(initial);

  useEffect(() => {
    fetch("/api/books")
      .then((res) => res.json())
      .then((data: { books: Book[] }) => setBooks(data.books));
  }, []);

  const needle = query.trim().toLowerCase();
  const matches = (books ?? []).filter(
    (b) => b.title.toLowerCase().includes(needle) || b.author.toLowerCase().includes(needle),
  );

  return (
    <>
      <label htmlFor="q">Title or author</label>{" "}
      <input id="q" type="search" value={query} onChange={(e) => setQuery(e.target.value)} />
      {books === null ? (
        <p role="status">Loading books...</p>
      ) : matches.length === 0 ? (
        <p role="status">No books match.</p>
      ) : (
        <ul className="book-list">
          {matches.map((book) => (
            <BookCard key={book.slug} book={book} />
          ))}
        </ul>
      )}
    </>
  );
}
