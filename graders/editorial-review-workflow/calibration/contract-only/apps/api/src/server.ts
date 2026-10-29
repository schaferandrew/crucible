import { createApp } from "./app";
import { createDb } from "./db";
import { seed } from "./seed";

const port = Number(process.env.PORT ?? 3000);
const db = createDb();
if (process.env.SEED !== "0") seed(db);
// EDITORS=ada,grace: the usernames who review submitted articles
const editors = (process.env.EDITORS ?? "").split(",").map((e) => e.trim()).filter(Boolean);

createApp(db, { editors }).listen(port, () => {
  console.log(`Conduit API on http://localhost:${port}/api`);
});
