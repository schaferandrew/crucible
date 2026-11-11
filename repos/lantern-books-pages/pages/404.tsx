import Head from "next/head";
import Link from "next/link";

export default function NotFound() {
  return (
    <>
      <Head>
        <title>Page not found | Lantern Books</title>
      </Head>
      <h1>Page not found</h1>
      <p>
        We could not find that page. <Link href="/">Back to the shop</Link>.
      </p>
    </>
  );
}
