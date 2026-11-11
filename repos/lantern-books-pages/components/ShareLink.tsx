import { useRouter } from "next/router";

/** The book's permanent address, read from the route. */
export default function ShareLink() {
  const { slug } = useRouter().query;
  return (
    <p className="permalink">
      Permalink: <code>/books/{slug}</code>
    </p>
  );
}
