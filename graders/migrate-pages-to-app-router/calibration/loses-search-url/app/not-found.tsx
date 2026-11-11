import Link from "next/link";

export default function NotFound() {
  return (
    <>
      <h1>Page not found</h1>
      <p>
        We could not find that page. <Link href="/">Back to the shop</Link>.
      </p>
    </>
  );
}
