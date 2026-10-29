import { createApp } from "./app";
import { createDb } from "./db";
import { seed } from "./seed";

const port = Number(process.env.PORT ?? 3000);
const db = createDb();
if (process.env.SEED !== "0") seed(db);

const responseCacheTtlMs = process.env.NODE_ENV === "production" ? 60_000 : undefined;

createApp(db, { responseCacheTtlMs }).listen(port, () => {
  console.log(`Conduit API on http://localhost:${port}/api`);
});
