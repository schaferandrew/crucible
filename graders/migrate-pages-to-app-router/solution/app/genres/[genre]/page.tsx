import type { Metadata } from "next";
import { notFound } from "next/navigation";
import BookCard from "../../../components/BookCard";
import { GENRES, booksByGenre, getGenreSlugs, isGenre } from "../../../lib/books";

// getStaticPaths with fallback: false: only these genres exist
export const dynamicParams = false;

export function generateStaticParams() {
  return getGenreSlugs().map((genre) => ({ genre }));
}

type Props = { params: { genre: string } };

export function generateMetadata({ params }: Props): Metadata {
  if (!isGenre(params.genre)) return {};
  const name = GENRES[params.genre];
  return { title: `${name} books`, description: `Browse our ${name.toLowerCase()} shelf.` };
}

export default function GenrePage({ params }: Props) {
  if (!isGenre(params.genre)) notFound();
  const name = GENRES[params.genre];
  const books = booksByGenre(params.genre);
  return (
    <>
      <h1>{name}</h1>
      <p className="lede">
        {books.length} {books.length === 1 ? "title" : "titles"} on this shelf.
      </p>
      <ul className="book-list">
        {books.map((book) => (
          <BookCard key={book.slug} book={book} />
        ))}
      </ul>
    </>
  );
}
