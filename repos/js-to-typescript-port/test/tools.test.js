import { describe, expect, it } from "vitest";
import { ToolStore } from "../src/store";
import { addTool, auditLines, findTools, loanTool, overdueTools, retireTool, returnTool } from "../src/tools";
import { addDays, daysBetween } from "../src/dates";
import { SEED, tempData } from "./helpers";

const fresh = () => new ToolStore(tempData()).load();

describe("dates", () => {
  it("adds days across month ends", () => {
    expect(addDays("2025-02-27", 3)).toBe("2025-03-02");
  });
  it("counts days between dates, negative when reversed", () => {
    expect(daysBetween("2025-03-01", "2025-03-04")).toBe(3);
    expect(daysBetween("2025-03-04", "2025-03-01")).toBe(-3);
  });
});

describe("store", () => {
  it("loads tools and fills in missing fields", () => {
    const store = fresh();
    expect(store.tools).toHaveLength(3);
    expect(store.get(1).tags).toEqual(["drill"]);
    expect(store.get(2).borrower).toBeNull();
    expect(store.get(3).replacementCost).toBeNull();
  });
  it("starts empty when the file does not exist", () => {
    const store = new ToolStore("/nonexistent/tools.json").load();
    expect(store.tools).toEqual([]);
    expect(store.nextId).toBe(1);
  });
  it("rejects a tool with an unknown status", () => {
    const bad = { ...SEED, tools: [{ id: 1, name: "Saw", status: "lost" }] };
    expect(() => new ToolStore(tempData(bad)).load()).toThrow('tool 1: bad status "lost"');
  });
});

describe("lending rules", () => {
  it("loans an available tool and sets the due date", () => {
    const store = fresh();
    const tool = loanTool(store, 2, " Ana ", 7, "2025-03-10");
    expect(tool).toMatchObject({ status: "loaned", borrower: "Ana", dueDate: "2025-03-17" });
  });
  it("refuses to loan a tool that is out or retired", () => {
    const store = fresh();
    expect(() => loanTool(store, 1, "ana", 7, "2025-03-10")).toThrow("tool 1 is loaned, not available");
    expect(() => loanTool(store, 3, "ana", 7, "2025-03-10")).toThrow("tool 3 is retired, not available");
  });
  it("limits loan length", () => {
    const store = fresh();
    expect(() => loanTool(store, 2, "ana", 29, "2025-03-10")).toThrow("loans run 1 to 28 days, not 29");
    expect(() => loanTool(store, 2, "ana", 1.5, "2025-03-10")).toThrow("not 1.5");
  });
  it("reports how late a return is", () => {
    const store = fresh();
    const { tool, lateDays } = returnTool(store, 1, "2025-03-10");
    expect(lateDays).toBe(7);
    expect(tool).toMatchObject({ status: "available", borrower: null, dueDate: null });
  });
  it("will not retire a tool that is out", () => {
    expect(() => retireTool(fresh(), 1, "worn")).toThrow("tool 1 is on loan to mina");
  });
  it("adds a tool with the next id", () => {
    const store = fresh();
    const tool = addTool(store, { name: "Level", category: "measure", tags: ["a"] });
    expect(tool.id).toBe(4);
    expect(tool.replacementCost).toBeNull();
  });
});

describe("queries", () => {
  it("filters by status, tag and text", () => {
    const store = fresh();
    expect(findTools(store, { status: "available" }).map((t) => t.id)).toEqual([2]);
    expect(findTools(store, { tag: "DRILL" }).map((t) => t.id)).toEqual([1]);
    expect(findTools(store, { text: "HAMMER" }).map((t) => t.id)).toEqual([2]);
  });
  it("rejects an unknown status filter", () => {
    expect(() => findTools(fresh(), { status: "broken" })).toThrow('unknown status "broken"');
  });
  it("lists overdue loans", () => {
    const store = fresh();
    expect(overdueTools(store, "2025-03-04").map((t) => t.id)).toEqual([1]);
    expect(overdueTools(store, "2025-03-03")).toEqual([]);
  });
});

describe("audit log", () => {
  it("writes one line per change", () => {
    const store = fresh();
    const lines = auditLines(store);
    loanTool(store, 2, "ana", 3, "2025-03-10");
    returnTool(store, 2, "2025-03-15");
    retireTool(store, 2, "rusted");
    expect(lines).toEqual([
      "loaned #2 to ana until 2025-03-13",
      "returned #2 from ana (2d late)",
      "retired #2: rusted",
    ]);
  });
});
