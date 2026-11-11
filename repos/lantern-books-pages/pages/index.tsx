import Head from "next/head";
import type { GetStaticProps } from "next";
import BookCard from "../components/BookCard";
import { getAllBooks, type Book } from "../lib/books";

type Props = { books: Book[]; inStock: number };

export const getStaticProps: GetStaticProps<Props> = async () => {
  const books = getAllBooks();
  return { props: { books, inStock: books.filter((b) => b.inStock).length } };
};

export default function Home({ books, inStock }: Props) {
  return (
    <>
      <Head>
        <title>Lantern Books</title>
        <meta name="description" content="An independent bookshop with new and notable titles." />
      </Head>
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
