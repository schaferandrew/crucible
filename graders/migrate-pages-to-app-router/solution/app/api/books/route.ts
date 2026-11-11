import { NextResponse } from "next/server";
import { booksByGenre, getAllBooks, isGenre } from "../../../lib/books";

export const dynamic = "force-dynamic";

export function GET(request: Request) {
  const genre = new URL(request.url).searchParams.get("genre");
  if (genre === null) return NextResponse.json({ books: getAllBooks() });
  if (!isGenre(genre)) return NextResponse.json({ error: "Unknown genre" }, { status: 400 });
  return NextResponse.json({ books: booksByGenre(genre) });
}
