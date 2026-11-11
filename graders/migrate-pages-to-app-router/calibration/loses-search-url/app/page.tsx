import type { Metadata } from "next";
import BookCard from "../components/BookCard";
import { getAllBooks } from "../lib/books";

export const metadata: Metadata = {
  title: { absolute: "Lantern Books" },
  description: "An independent bookshop with new and notable titles.",
};

export default function Home() {
  const books = getAllBooks();
  const inStock = books.filter((b) => b.inStock).length;
  return (
    <>
      <h1>Lantern Books</h1>
      <p className="lede">
        {books.length} titles, {inStock} in stock.
      </p>
      <ul className="book-list">
        {books.map((book) => (
          <BookCard key={book.slug} book={book} />
        ))}
      </ul>
    </>
  );
}
