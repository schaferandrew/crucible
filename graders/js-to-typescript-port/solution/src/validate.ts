// Turns one raw record from the JSON file into a tool. Older files leave fields out.

import { isIsoDate } from "./dates.js";
import { STATUSES, type Tool, type ToolStatus } from "./types.js";

export { STATUSES };

export function isStatus(value: unknown): value is ToolStatus {
  return (STATUSES as readonly unknown[]).includes(value);
}

export function normalizeTool(input: unknown): Tool {
  if (!input || typeof input !== "object") throw new Error("tool record must be an object");
  const raw = input as Record<string, unknown>;
  const id = Number(raw.id);
  if (!Number.isInteger(id) || id < 1) throw new Error(`bad tool id ${JSON.stringify(raw.id)}`);
  if (typeof raw.name !== "string" || raw.name.trim() === "") throw new Error(`tool ${id}: name is required`);
  const status = raw.status;
  if (!isStatus(status)) throw new Error(`tool ${id}: bad status ${JSON.stringify(raw.status)}`);
  const borrower = raw.borrower;
  const dueDate = raw.dueDate;
  if (status === "loaned" && !(borrower && isIsoDate(dueDate))) {
    throw new Error(`tool ${id}: a loaned tool needs a borrower and a due date`);
  }
  const loaned = status === "loaned";
  return {
    id,
    name: raw.name.trim(),
    category: (raw.category as string | undefined) || "general",
    tags: Array.isArray(raw.tags) ? raw.tags.map((t) => String(t).toLowerCase()) : [],
    status,
    borrower: loaned ? (borrower as string) : null,
    dueDate: loaned ? (dueDate as string) : null,
    retiredReason: status === "retired" ? (raw.retiredReason as string | undefined) || "unknown" : null,
    replacementCost: typeof raw.replacementCost === "number" ? raw.replacementCost : null,
  };
}
