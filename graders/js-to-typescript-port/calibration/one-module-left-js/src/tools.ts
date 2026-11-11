// The lending rules. Every function takes the store; `today` is always passed in ("YYYY-MM-DD").

import { addDays, daysBetween } from "./dates.js";
import type { ToolStore } from "./store.js";
import type { Tool, ToolStatus } from "./types.js";
import { isStatus } from "./validate.js";

export const MAX_LOAN_DAYS = 28;

function requireTool(store: ToolStore, id: number): Tool {
  const tool = store.get(id);
  if (!tool) throw new Error(`no tool with id ${id}`);
  return tool;
}

export interface NewTool {
  name: string;
  category?: string;
  tags?: string[];
  replacementCost?: number;
}

export function addTool(store: ToolStore, { name, category, tags, replacementCost }: NewTool): Tool {
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

export function loanTool(store: ToolStore, id: number, borrower: string, days: number, today: string): Tool {
  const tool = requireTool(store, id);
  if (tool.status !== "available") throw new Error(`tool ${id} is ${tool.status}, not available`);
  if (!borrower || !borrower.trim()) throw new Error("a loan needs a borrower");
  if (!Number.isInteger(days) || days < 1 || days > MAX_LOAN_DAYS) {
    throw new Error(`loans run 1 to ${MAX_LOAN_DAYS} days, not ${days}`);
  }
  const dueDate = addDays(today, days);
  tool.status = "loaned";
  tool.borrower = borrower.trim();
  tool.dueDate = dueDate;
  store.emit({ type: "loaned", tool, borrower: tool.borrower, dueDate });
  return tool;
}

export function returnTool(store: ToolStore, id: number, today: string): { tool: Tool; lateDays: number } {
  const tool = requireTool(store, id);
  if (tool.status !== "loaned" || tool.dueDate === null) throw new Error(`tool ${id} is ${tool.status}, not on loan`);
  const lateDays = Math.max(0, daysBetween(tool.dueDate, today));
  const borrower = tool.borrower;
  tool.status = "available";
  tool.borrower = null;
  tool.dueDate = null;
  store.emit({ type: "returned", tool, borrower, lateDays });
  return { tool, lateDays };
}

export function retireTool(store: ToolStore, id: number, reason?: string): Tool {
  const tool = requireTool(store, id);
  if (tool.status === "loaned") throw new Error(`tool ${id} is on loan to ${tool.borrower}`);
  if (tool.status === "retired") throw new Error(`tool ${id} is already retired`);
  const why = reason && reason.trim() ? reason.trim() : "unknown";
  tool.status = "retired";
  tool.retiredReason = why;
  store.emit({ type: "retired", tool, reason: why });
  return tool;
}

export interface ToolQuery {
  text?: string;
  status?: string;
  tag?: string;
}

export function findTools(store: ToolStore, { text, status, tag }: ToolQuery = {}): Tool[] {
  let wantedStatus: ToolStatus | undefined;
  if (status !== undefined) {
    if (!isStatus(status)) throw new Error(`unknown status "${status}"`);
    wantedStatus = status;
  }
  const needle = text ? text.toLowerCase() : null;
  const wanted = tag ? tag.toLowerCase() : null;
  return store.tools.filter((tool) => {
    if (wantedStatus && tool.status !== wantedStatus) return false;
    if (wanted && !tool.tags.includes(wanted)) return false;
    if (needle) {
      const haystack = [tool.name, tool.category, ...tool.tags].join(" ").toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });
}

// Loans past their due date, the longest overdue first (ties by id).
export function overdueTools(store: ToolStore, today: string): Tool[] {
  return store.tools
    .filter((tool) => tool.dueDate !== null && tool.dueDate < today)
    .sort((a, b) => (a.dueDate ?? "").localeCompare(b.dueDate ?? "") || a.id - b.id);
}

// One line per change, for the audit log. Listeners get a different event for each kind of change.
export function auditLines(store: ToolStore): string[] {
  const lines: string[] = [];
  store.on((event) => {
    switch (event.type) {
      case "added":
        lines.push(`added #${event.tool.id} ${event.tool.name}`);
        break;
      case "loaned":
        lines.push(`loaned #${event.tool.id} to ${event.borrower} until ${event.dueDate}`);
        break;
      case "returned": {
        const late = event.lateDays > 0 ? ` (${event.lateDays}d late)` : "";
        lines.push(`returned #${event.tool.id} from ${event.borrower}${late}`);
        break;
      }
      case "retired":
        lines.push(`retired #${event.tool.id}: ${event.reason}`);
        break;
    }
  });
  return lines;
}
