"use client";

import { useParams } from "next/navigation";

/** The book's permanent address, read from the route. */
export default function ShareLink() {
  const { slug } = useParams<{ slug: string }>();
  return (
    <p className="permalink">
      Permalink: <code>/books/{slug}</code>
    </p>
  );
}
