import type { Metadata } from "next";
import { Suspense } from "react";
import SearchClient from "./SearchClient";

export const metadata: Metadata = {
  title: "Search",
  description: "Search the shop by title or author.",
};

export default function SearchPage() {
  return (
    <>
      <h1>Search the shop</h1>
      <Suspense fallback={<p role="status">Loading books...</p>}>
        <SearchClient />
      </Suspense>
    </>
  );
}
