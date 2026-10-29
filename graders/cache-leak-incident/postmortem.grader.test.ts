// Hidden tests for cache-leak-incident: the postmortem's fixed lines (the prompt spells them out). Each line is
// one test, so a stray number elsewhere in the file earns nothing. incident/POSTMORTEM.md is one of the grader's
// artifacts; the tests run from apps/api. Times and the count come from the incident logs (ground_truth.json).
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const file = resolve(process.cwd(), "../../incident/POSTMORTEM.md");
const text = existsSync(file) ? readFileSync(file, "utf8") : "";

// "Label: value" at the start of a line, tolerating a list marker, bold or backticks around it
function field(label: string): string | undefined {
  const line = new RegExp(`^[ \\t>*_\`-]*${label}[*_\`]*:[*_\`]*[ \\t]*(.*)$`, "im").exec(text);
  return line?.[1];
}
const time = (label: string) => /(?:\d{4}-\d{2}-\d{2}T)?(\d{2}:\d{2}:\d{2})/.exec(field(label) ?? "")?.[1];

describe("postmortem: lines from the logs", () => {
  it("Deploy: 16:42:10", () => {
    expect(time("Deploy")).toBe("16:42:10");
  });

  it("First affected request: 16:44:15", () => {
    expect(time("First affected request")).toBe("16:44:15");
  });

  it("First report: 18:06:01", () => {
    expect(time("First report")).toBe("18:06:01");
  });

  it("Affected users: 371 (or 481, with the anonymous-stored responses counted and said)", () => {
    const n = /\b\d[\d,]*\b/.exec(field("Affected users") ?? "")?.[0].replace(/,/g, "");
    if (n === "481") expect(text).toMatch(/anonymous|signed[- ]out|logged[- ]out|unauthenticated/i);
    else expect(n).toBe("371");
  });
});
