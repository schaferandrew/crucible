// Turns one raw record from the JSON file into a tool. Older files leave fields out.

import { isIsoDate } from "./dates.js";

export const STATUSES = ["available", "loaned", "retired"];

export function isStatus(value) {
  return STATUSES.includes(value);
}

export function normalizeTool(raw) {
  if (!raw || typeof raw !== "object") throw new Error("tool record must be an object");
  const id = Number(raw.id);
  if (!Number.isInteger(id) || id < 1) throw new Error(`bad tool id ${JSON.stringify(raw.id)}`);
  if (typeof raw.name !== "string" || raw.name.trim() === "") throw new Error(`tool ${id}: name is required`);
  if (!isStatus(raw.status)) throw new Error(`tool ${id}: bad status ${JSON.stringify(raw.status)}`);
  if (raw.status === "loaned" && !(raw.borrower && isIsoDate(raw.dueDate))) {
    throw new Error(`tool ${id}: a loaned tool needs a borrower and a due date`);
  }
  return {
    id,
    name: raw.name.trim(),
    category: raw.category || "general",
    tags: Array.isArray(raw.tags) ? raw.tags.map((t) => String(t).toLowerCase()) : [],
    status: raw.status,
    borrower: raw.status === "loaned" ? raw.borrower : null,
    dueDate: raw.status === "loaned" ? raw.dueDate : null,
    retiredReason: raw.status === "retired" ? raw.retiredReason || "unknown" : null,
    replacementCost: typeof raw.replacementCost === "number" ? raw.replacementCost : null,
  };
}
