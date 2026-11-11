import Head from "next/head";
import { useRouter } from "next/router";
import { useEffect, useState } from "react";
import BookCard from "../components/BookCard";
import type { Book } from "../lib/books";

export default function Search() {
  const router = useRouter();
  const [books, setBooks] = useState<Book[] | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    fetch("/api/books")
      .then((res) => res.json())
      .then((data: { books: Book[] }) => setBooks(data.books));
  }, []);

  useEffect(() => {
    if (router.isReady && typeof router.query.q === "string") setQuery(router.query.q);
  }, [router.isReady, router.query.q]);

  const needle = query.trim().toLowerCase();
  const matches = (books ?? []).filter(
    (b) => b.title.toLowerCase().includes(needle) || b.author.toLowerCase().includes(needle),
  );

  return (
    <>
      <Head>
        <title>Search | Lantern Books</title>
        <meta name="description" content="Search the shop by title or author." />
      </Head>
      <h1>Search the shop</h1>
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
