// The lending rules. Every function takes the store; `today` is always passed in ("YYYY-MM-DD").

import { addDays, daysBetween } from "./dates.js";
import { isStatus } from "./validate.js";

export const MAX_LOAN_DAYS = 28;

function requireTool(store, id) {
  const tool = store.get(id);
  if (!tool) throw new Error(`no tool with id ${id}`);
  return tool;
}

export function addTool(store, { name, category, tags, replacementCost }) {
  if (!name || !name.trim()) throw new Error("a tool needs a name");
  const tool = store.insert({
    name,
    category,
    tags: tags || [],
    replacementCost: replacementCost === undefined ? null : replacementCost,
  });
  store.emit({ type: "added", tool });
  return tool;
}

export function loanTool(store, id, borrower, days, today) {
  const tool = requireTool(store, id);
  if (tool.status !== "available") throw new Error(`tool ${id} is ${tool.status}, not available`);
  if (!borrower || !borrower.trim()) throw new Error("a loan needs a borrower");
  if (!Number.isInteger(days) || days < 1 || days > MAX_LOAN_DAYS) {
    throw new Error(`loans run 1 to ${MAX_LOAN_DAYS} days, not ${days}`);
  }
  tool.status = "loaned";
  tool.borrower = borrower.trim();
  tool.dueDate = addDays(today, days);
  store.emit({ type: "loaned", tool, borrower: tool.borrower, dueDate: tool.dueDate });
  return tool;
}

export function returnTool(store, id, today) {
  const tool = requireTool(store, id);
  if (tool.status !== "loaned") throw new Error(`tool ${id} is ${tool.status}, not on loan`);
  const lateDays = Math.max(0, daysBetween(tool.dueDate, today));
  const borrower = tool.borrower;
  tool.status = "available";
  tool.borrower = null;
  tool.dueDate = null;
  store.emit({ type: "returned", tool, borrower, lateDays });
  return { tool, lateDays };
}

export function retireTool(store, id, reason) {
  const tool = requireTool(store, id);
  if (tool.status === "loaned") throw new Error(`tool ${id} is on loan to ${tool.borrower}`);
  if (tool.status === "retired") throw new Error(`tool ${id} is already retired`);
  tool.status = "retired";
  tool.retiredReason = reason && reason.trim() ? reason.trim() : "unknown";
  store.emit({ type: "retired", tool, reason: tool.retiredReason });
  return tool;
}

export function findTools(store, { text, status, tag } = {}) {
  if (status !== undefined && !isStatus(status)) throw new Error(`unknown status "${status}"`);
  const needle = text ? text.toLowerCase() : null;
  const wanted = tag ? tag.toLowerCase() : null;
  return store.tools.filter((tool) => {
    if (status && tool.status !== status) return false;
    if (wanted && !tool.tags.includes(wanted)) return false;
    if (needle) {
      const haystack = [tool.name, tool.category, ...tool.tags].join(" ").toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });
}

// Loans past their due date, the longest overdue first (ties by id).
export function overdueTools(store, today) {
  return store.tools
    .filter((tool) => tool.dueDate && tool.dueDate < today)
    .sort((a, b) => a.dueDate.localeCompare(b.dueDate) || a.id - b.id);
}

// One line per change, for the audit log. Listeners get a different event for each kind of change.
export function auditLines(store) {
  const lines = [];
  store.on((event) => {
    if (event.type === "added") lines.push(`added #${event.tool.id} ${event.tool.name}`);
    else if (event.type === "loaned") lines.push(`loaned #${event.tool.id} to ${event.borrower} until ${event.dueDate}`);
    else if (event.type === "returned") {
      const late = event.lateDays > 0 ? ` (${event.lateDays}d late)` : "";
      lines.push(`returned #${event.tool.id} from ${event.borrower}${late}`);
    } else lines.push(`retired #${event.tool.id}: ${event.reason}`);
  });
  return lines;
}
