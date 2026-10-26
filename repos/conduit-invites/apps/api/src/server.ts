import { createApp } from "./app";
import { createDb } from "./db";
import { seed } from "./seed";

const port = Number(process.env.PORT ?? 3000);
const db = createDb();
if (process.env.SEED !== "0") seed(db);

createApp(db).listen(port, () => {
  console.log(`Conduit API on http://localhost:${port}/api`);
});
