import data from "../data/books.json";

export type Genre = "fiction" | "science" | "history";

export type Book = {
  slug: string;
  title: string;
  author: string;
  genre: Genre;
  price: number; // cents
  year: number;
  inStock: boolean;
  summary: string;
};

export const GENRES: Record<Genre, string> = {
  fiction: "Fiction",
  science: "Science",
  history: "History",
};

const all = data as Book[];

/** Every book, sorted by title. */
export function getAllBooks(): Book[] {
  return [...all].sort((a, b) => a.title.localeCompare(b.title));
}

export function getBook(slug: string): Book | undefined {
  return all.find((book) => book.slug === slug);
}

export function isGenre(value: string): value is Genre {
  return Object.prototype.hasOwnProperty.call(GENRES, value);
}

export function getGenreSlugs(): Genre[] {
  return Object.keys(GENRES) as Genre[];
}

export function booksByGenre(genre: Genre): Book[] {
  return getAllBooks().filter((book) => book.genre === genre);
}

export function formatPrice(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}
