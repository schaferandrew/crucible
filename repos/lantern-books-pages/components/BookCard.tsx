import Link from "next/link";
import { formatPrice, type Book } from "../lib/books";

export default function BookCard({ book }: { book: Book }) {
  return (
    <li className="card">
      <Link href={`/books/${book.slug}`}>{book.title}</Link>
      <span className="card-author"> by {book.author}</span>
      <span className="card-price">{formatPrice(book.price)}</span>
    </li>
  );
}
