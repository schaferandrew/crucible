import fs from "node:fs";
import { describe, expect, it } from "vitest";
import { main, parseArgs } from "../src/cli";
import { capture, tempData } from "./helpers";

function run(argv, file = tempData()) {
  const { lines, out } = capture();
  const code = main(argv, { file, today: "2025-03-10", out });
  return { code, lines, file };
}

describe("parseArgs", () => {
  it("separates positionals from flags", () => {
    expect(parseArgs(["loan", "2", "ana", "--days", "5", "--quiet"])).toEqual({
      command: "loan",
      args: ["2", "ana"],
      flags: { days: "5", quiet: true },
    });
  });
});

describe("commands", () => {
  it("lists tools as a table", () => {
    const { code, lines } = run(["list"]);
    expect(code).toBe(0);
    expect(lines[0]).toContain("#1  Cordless drill  power   loaned     mina, due 2025-03-03");
  });
  it("loans a tool and saves it", () => {
    const { code, lines, file } = run(["loan", "2", "ana", "--days", "5"]);
    expect(code).toBe(0);
    expect(lines).toEqual(["#2 Claw hammer loaned to ana until 2025-03-15"]);
    expect(JSON.parse(fs.readFileSync(file, "utf8")).tools[1].status).toBe("loaned");
  });
  it("exits 1 when a rule is broken and leaves the file alone", () => {
    const file = tempData();
    const before = fs.readFileSync(file, "utf8");
    const { code, lines } = run(["loan", "1", "ana"], file);
    expect(code).toBe(1);
    expect(lines).toEqual(["error: tool 1 is loaned, not available"]);
    expect(fs.readFileSync(file, "utf8")).toBe(before);
  });
  it("exits 2 on bad usage", () => {
    expect(run(["frobnicate"]).code).toBe(2);
    expect(run(["return", "abc"]).lines).toEqual(['error: "abc" is not a tool id']);
  });
  it("prints the report", () => {
    const [report] = run(["report"]).lines;
    const rows = report.split("\n");
    expect(rows[0]).toBe("3 tools: 1 available, 1 loaned, 1 retired");
    expect(rows[2]).toBe("overdue: 1");
  });
});
