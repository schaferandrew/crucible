import Head from "next/head";
import type { GetStaticPaths, GetStaticProps } from "next";
import BookCard from "../../components/BookCard";
import { GENRES, booksByGenre, getGenreSlugs, isGenre, type Book } from "../../lib/books";

type Props = { name: string; books: Book[] };

export const getStaticPaths: GetStaticPaths = async () => ({
  paths: getGenreSlugs().map((genre) => ({ params: { genre } })),
  fallback: false,
});

export const getStaticProps: GetStaticProps<Props> = async ({ params }) => {
  const genre = String(params?.genre);
  if (!isGenre(genre)) return { notFound: true };
  return { props: { name: GENRES[genre], books: booksByGenre(genre) } };
};

export default function GenrePage({ name, books }: Props) {
  return (
    <>
      <Head>
        <title>{`${name} books | Lantern Books`}</title>
        <meta name="description" content={`Browse our ${name.toLowerCase()} shelf.`} />
      </Head>
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
