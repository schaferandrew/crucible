import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import ShareLink from "../../../components/ShareLink";
import { GENRES, formatPrice, getAllBooks, getBook } from "../../../lib/books";
import { recordView, viewsLabel } from "../../../lib/views";

export function generateStaticParams() {
  return getAllBooks().map((b) => ({ slug: b.slug }));
}

type Props = { params: { slug: string } };

export function generateMetadata({ params }: Props): Metadata {
  const book = getBook(params.slug);
  if (!book) notFound();
  return { title: `${book.title} by ${book.author}`, description: book.summary };
}

export default function BookPage({ params }: Props) {
  const book = getBook(params.slug);
  if (!book) notFound();
  const views = recordView(book.slug);
  return (
    <article>
      <h1>{book.title}</h1>
      <p className="byline">
        by {book.author}, {book.year}
      </p>
      <p className="price">{formatPrice(book.price)}</p>
      <p className="stock">{book.inStock ? "In stock" : "Out of stock"}</p>
      <p>
        Genre: <Link href={`/genres/${book.genre}`}>{GENRES[book.genre]}</Link>
      </p>
      <p>{book.summary}</p>
      <p className="views">{viewsLabel(views)}</p>
      <ShareLink />
    </article>
  );
}
