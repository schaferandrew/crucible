import Head from "next/head";
import Link from "next/link";
import type { GetServerSideProps } from "next";
import ShareLink from "../../components/ShareLink";
import { GENRES, formatPrice, getBook, type Book } from "../../lib/books";
import { recordView, viewsLabel } from "../../lib/views";

type Props = { book: Book; views: number };

export const getServerSideProps: GetServerSideProps<Props> = async ({ params }) => {
  const book = getBook(String(params?.slug));
  if (!book) return { notFound: true };
  return { props: { book, views: recordView(book.slug) } };
};

export default function BookPage({ book, views }: Props) {
  return (
    <>
      <Head>
        <title>{`${book.title} by ${book.author} | Lantern Books`}</title>
        <meta name="description" content={book.summary} />
      </Head>
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
    </>
  );
}
