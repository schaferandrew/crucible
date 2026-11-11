import { describe, expect, it } from "vitest";
import { recordView, viewsLabel } from "./views";

describe("views", () => {
  it("counts each view of a book separately", () => {
    expect(recordView("a")).toBe(1);
    expect(recordView("a")).toBe(2);
    expect(recordView("b")).toBe(1);
  });

  it("words the count", () => {
    expect(viewsLabel(1)).toBe("Viewed 1 time");
    expect(viewsLabel(3)).toBe("Viewed 3 times");
  });
});
