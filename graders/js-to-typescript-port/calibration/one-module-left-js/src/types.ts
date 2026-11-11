export const STATUSES = ["available", "loaned", "retired"] as const;

export type ToolStatus = (typeof STATUSES)[number];

export interface Tool {
  id: number;
  name: string;
  category: string;
  tags: string[];
  status: ToolStatus;
  borrower: string | null;
  dueDate: string | null;
  retiredReason: string | null;
  replacementCost: number | null;
}

export type ToolEvent =
  | { type: "added"; tool: Tool }
  | { type: "loaned"; tool: Tool; borrower: string; dueDate: string }
  | { type: "returned"; tool: Tool; borrower: string | null; lateDays: number }
  | { type: "retired"; tool: Tool; reason: string };

export type ToolListener = (event: ToolEvent) => void;

export interface Summary {
  total: number;
  byStatus: Record<ToolStatus, number>;
  byCategory: Record<string, number>;
  overdue: number;
  unpriced: number;
  insuredValue: number;
}
