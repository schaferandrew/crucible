import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const SEED = {
  nextId: 4,
  tools: [
    { id: 1, name: "Cordless drill", category: "power", tags: ["Drill"], status: "loaned", borrower: "mina", dueDate: "2025-03-03", replacementCost: 89.5 },
    { id: 2, name: "Claw hammer", category: "hand", tags: ["striking"], status: "available", replacementCost: 18.25 },
    { id: 3, name: "Garden fork", category: "garden", status: "retired", retiredReason: "snapped handle" },
  ],
};

export function tempData(data = SEED) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "toolshed-"));
  const file = path.join(dir, "tools.json");
  fs.writeFileSync(file, JSON.stringify(data));
  return file;
}

export function capture() {
  const lines = [];
  return { lines, out: (line) => lines.push(line) };
}
