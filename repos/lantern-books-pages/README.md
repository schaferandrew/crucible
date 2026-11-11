# Lantern Books

A small bookshop site on Next.js 14 (Pages Router).

- `pages/`: the routes (`/`, `/books/[slug]`, `/genres/[genre]`, `/search`, `/about`, a custom 404) and `pages/api/books.ts`
- `components/`: shared UI (`Layout` wraps every page from `pages/_app.tsx`)
- `lib/`: the book data helpers and a view counter; `data/books.json` is the catalogue
- `styles/globals.css`: the site's styles

```bash
npm run dev     # http://localhost:3000
npm test        # vitest
npm run build
```
