import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ReadMore } from "../src/components/ReadMore";
import { TagFilter } from "../src/components/TagFilter";
import { Toast } from "../src/components/Toast";

describe("accessibility", () => {
  it("Read more is a keyboard-operable button that reports its state", async () => {
    const user = userEvent.setup();
    render(<ReadMore text={"word ".repeat(40)} limit={20} />);
    await user.tab();
    const control = screen.getByRole("button", { name: /read more/i });
    expect(control).toHaveFocus();
    expect(control).toHaveAttribute("aria-expanded", "false");
    await user.keyboard("{Enter}");
    expect(control).toHaveAttribute("aria-expanded", "true");
  });

  it("the tag filter is a named native control", async () => {
    const user = userEvent.setup();
    render(<TagFilter tags={["a", "b"]} value={null} onChange={() => {}} />);
    await user.tab();
    expect(screen.getByRole("combobox", { name: /tag/i })).toHaveFocus();
  });

  it("the toast sits in a live region that is there before the message", () => {
    const { rerender } = render(<Toast message={null} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    rerender(<Toast message="Article published" />);
    expect(screen.getByRole("status")).toHaveTextContent("Article published");
  });
});
