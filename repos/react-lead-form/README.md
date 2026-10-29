# Brightline Windows site

A small Next.js 14 (App Router) site. The quote request form lives at `/contact`:

- `app/contact/page.tsx`: the page
- `app/contact/LeadForm.tsx`: the form
- `app/api/leads/route.ts`: `POST /api/leads`, which saves a lead
- `lib/leads.ts`: the lead store, a JSON file at `LEADS_FILE` (default `data/leads.json`)

```bash
npm run dev     # http://localhost:3000/contact
npm test        # vitest
npm run build
```
