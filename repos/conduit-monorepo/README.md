# Conduit

A [RealWorld](https://realworld.how) implementation: a Medium-style blogging platform with users, profiles, articles, comments, favorites, follows and tags.

```
apps/api         Express REST API implementing the RealWorld API spec
apps/web         React single-page app that talks to the API
packages/shared  Types, validation schemas and helpers shared by both
```

## Running

```bash
npm install
npm test            # every workspace's tests
npm run test:api    # API tests, including the RealWorld contract suite
npm run test:web    # web component tests
npm run dev:api     # API on http://localhost:3000 (PORT to override)
npm run dev:web     # web app on http://localhost:5173, proxying /api to the API
```

## Architecture

**API** (`apps/api`)

- `src/app.ts` builds the Express app from a `Db` (`createApp(db)`), so tests get a fresh in-memory database each time. `src/server.ts` is the only file that listens on a port.
- Requests flow `routes/` → `services/` → `repositories/` → `db.ts`. Routes handle HTTP and validation, services hold business rules (who may edit what, how a feed is built), and repositories are the only code that touches tables.
- `db.ts` is an in-memory store with the shape of a relational schema: tables keyed by id, with join tables for follows, favorites and article tags.
- Auth is a JWT in the `Authorization: Token <jwt>` header, as the RealWorld spec defines. `middleware/auth.ts` provides `requireAuth` and `optionalAuth`.
- Errors use the spec's envelope: `422 {"errors": {"body": ["..."]}}`, plus 401, 403 and 404.

**Web** (`apps/web`)

- `src/api/client.ts` is the only code that calls the API; it adds the token and unwraps the envelopes.
- `src/auth/AuthContext.tsx` holds the signed-in user.
- Pages live in `src/pages/`, shared pieces in `src/components/`.

**Shared** (`packages/shared`)

- `types.ts` defines the API's JSON shapes; both apps import them, so a change to a response shape is a type error everywhere it matters.
- `validation.ts` holds zod schemas the API validates request bodies with.

## Tests

- `apps/api/test/realworld.contract.test.ts` exercises the RealWorld API spec end to end. It must stay green: other RealWorld frontends depend on this contract.
- `apps/api/test/*.test.ts` cover services and edge cases.
- `apps/web/test/*.test.tsx` render components with Testing Library.
