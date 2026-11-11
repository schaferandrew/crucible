// Summaries and the text table.

import type { ToolStore } from "./store.js";
import { overdueTools } from "./tools.js";
import { STATUSES, type Summary, type Tool, type ToolStatus } from "./types.js";

export function summarize(store: ToolStore, today: string): Summary {
  const byStatus: any = { available: 0, loaned: 0, retired: 0 };
  const byCategory = store.tools.reduce<any>((counts, tool) => {
    counts[tool.category] = (counts[tool.category] || 0) + 1;
    return counts;
  }, {});
  const priced = store.tools.filter((tool) => tool.status !== "retired" && tool.replacementCost !== null);
  for (const tool of store.tools) byStatus[tool.status] += 1;
  return {
    total: store.tools.length,
    byStatus,
    byCategory,
    overdue: overdueTools(store, today).length,
    unpriced: store.tools.filter((tool) => tool.status !== "retired").length - priced.length,
    insuredValue: Math.round(priced.reduce((sum, tool) => sum + (tool.replacementCost ?? 0), 0) * 100) / 100,
  };
}

function detail(tool: Tool): string {
  if (tool.status === "loaned") return `${tool.borrower}, due ${tool.dueDate}`;
  if (tool.status === "retired") return tool.retiredReason ?? "";
  return "";
}

export function formatTable(tools: Tool[]): string {
  if (tools.length === 0) return "no tools";
  const rows = tools.map((tool) => [`#${tool.id}`, tool.name, tool.category, tool.status, detail(tool)]);
  const widths = [0, 1, 2, 3].map((col) => Math.max(...rows.map((row) => (row[col] ?? "").length)));
  return rows
    .map((row) => row.map((cell, col) => (col < 4 ? cell.padEnd(widths[col] ?? 0) : cell)).join("  ").trimEnd())
    .join("\n");
}

export function formatSummary(summary: Summary): string {
  const categories = Object.keys(summary.byCategory)
    .sort()
    .map((name) => `${name} ${summary.byCategory[name]}`)
    .join(", ");
  return [
    `${summary.total} tools: ${STATUSES.map((s) => `${summary.byStatus[s]} ${s}`).join(", ")}`,
    `categories: ${categories || "none"}`,
    `overdue: ${summary.overdue}`,
    `insured value: ${summary.insuredValue.toFixed(2)} (${summary.unpriced} without a price)`,
  ].join("\n");
}
