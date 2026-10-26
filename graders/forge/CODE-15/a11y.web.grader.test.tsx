// Hidden acceptance tests for C15 (accessibility). Never copied into the model's workspace.
// The judge copies this file to apps/web/test/hidden/ in a scratch copy and runs:
//   npx vitest run test/hidden    (from apps/web)
//
// Tests behavior, not markup: native elements (<dialog>, <select>, <details>) and ARIA-pattern
// widgets both pass when they behave correctly for keyboard and screen reader users.
// axe-core (the engine behind Lighthouse and Deque's tools) checks names, roles and states.
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../../src/api/client";
import { AuthProvider } from "../../src/auth/AuthContext";
import { ConfirmDialog } from "../../src/components/ConfirmDialog";
import { FavoriteButton } from "../../src/components/FavoriteButton";
import { ReadMore } from "../../src/components/ReadMore";
import { TagFilter } from "../../src/components/TagFilter";
import { Toast } from "../../src/components/Toast";
import { EditorPage } from "../../src/pages/EditorPage";
import { makeArticle } from "../render";

beforeAll(() => {
  // jsdom has <dialog> but not showModal/close; give native dialogs a fair chance
  const proto = HTMLDialogElement.prototype as HTMLDialogElement & { showModal?: () => void };
  if (!proto.showModal) {
    proto.showModal = function () { this.setAttribute("open", ""); };
    proto.show = function () { this.setAttribute("open", ""); };
    proto.close = function () { this.removeAttribute("open"); this.dispatchEvent(new Event("close")); };
  }
});

async function violations(container: Element) {
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false }, region: { enabled: false } } });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

function DialogHarness({ onConfirm = () => {} }: { onConfirm?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <a href="#before">Link before</a>
      <button type="button" onClick={() => setOpen(true)}>Delete Article</button>
      <a href="#after">Link after</a>
      <ConfirmDialog open={open} title="Delete this article?" message="This can't be undone."
        onConfirm={() => { onConfirm(); setOpen(false); }} onCancel={() => setOpen(false)} />
    </div>
  );
}

describe("finding 1: the delete confirmation", () => {
  it("is announced as a named dialog and takes focus", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    await user.click(screen.getByRole("button", { name: "Delete Article" }));
    const dialog = screen.getByRole("dialog", { name: /delete this article/i });
    expect(dialog.tagName === "DIALOG" || dialog.getAttribute("aria-modal") === "true").toBe(true);
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("keeps Tab and Shift+Tab inside, and its buttons work from the keyboard", async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(<DialogHarness onConfirm={onConfirm} />);
    await user.click(screen.getByRole("button", { name: "Delete Article" }));
    const dialog = screen.getByRole("dialog");
    for (let i = 0; i < 6; i++) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    for (let i = 0; i < 6; i++) {
      await user.tab({ shift: true });
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    const confirm = within(dialog).getByRole("button", { name: /delete/i });
    confirm.focus();
    await user.keyboard("{Enter}");
    expect(onConfirm).toHaveBeenCalled();
  });

  it("closes on Escape and returns focus to what opened it", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    const trigger = screen.getByRole("button", { name: "Delete Article" });
    await user.click(trigger);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("returns focus after Cancel too", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    const trigger = screen.getByRole("button", { name: "Delete Article" });
    await user.click(trigger);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: /cancel/i }));
    expect(document.activeElement).toBe(trigger);
  });
});

describe("finding 2: Read more", () => {
  const long = "Opening paragraph that sets the scene. ".repeat(6) + "The revealed ending only appears after expanding.";

  it("is a keyboard-reachable control that reports its state", async () => {
    const user = userEvent.setup();
    render(<ReadMore text={long} limit={60} />);
    await user.tab();
    const control = document.activeElement as HTMLElement;
    expect(control).toBeTruthy();
    expect(control.textContent).toMatch(/read more/i);
    const expandedBefore = control.getAttribute("aria-expanded") ?? (control.closest("details")?.open ? "true" : "false");
    expect(expandedBefore).toBe("false");
    await user.keyboard("{Enter}");
    expect(screen.getByText(/revealed ending/i)).toBeInTheDocument();
    const after = control.getAttribute("aria-expanded") ?? (control.closest("details")?.open ? "true" : "false");
    expect(after).toBe("true");
  });

  it("puts the revealed text where a screen reader user will hear it", async () => {
    const user = userEvent.setup();
    render(<ReadMore text={long} limit={60} />);
    await user.tab();
    const control = document.activeElement as HTMLElement;
    await user.keyboard("{Enter}");
    const revealed = screen.getByText(/revealed ending/i);
    const focusMovedToIt = revealed.contains(document.activeElement) || (document.activeElement as HTMLElement).contains(revealed);
    const controlled = control.getAttribute("aria-controls");
    const controlsIt = Boolean(controlled && document.getElementById(controlled)?.contains(revealed));
    const live = revealed.closest("[aria-live], [role=status], [role=log]");
    const disclosure = Boolean(control.closest("details")?.contains(revealed));
    expect(focusMovedToIt || controlsIt || Boolean(live) || disclosure).toBe(true);
  });
});

describe("finding 3: the tag filter", () => {
  it("can be used entirely from the keyboard", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<TagFilter tags={["design", "react", "rust"]} value={null} onChange={onChange} />);
    await user.tab();
    const trigger = document.activeElement as HTMLElement;
    expect(trigger).not.toBe(document.body);
    if (trigger.tagName === "SELECT") {
      await user.selectOptions(trigger, "react");
      expect(onChange).toHaveBeenCalledWith("react");
      return;
    }
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    await user.keyboard("{ArrowDown}");
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    const listbox = screen.getByRole("listbox");
    expect(within(listbox).getAllByRole("option").length).toBeGreaterThanOrEqual(3);
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalled();
    expect(typeof onChange.mock.calls[0][0] === "string" || onChange.mock.calls[0][0] === null).toBe(true);
  });

  it("closes on Escape with focus back on the trigger, and marks the selection", async () => {
    const user = userEvent.setup();
    render(<TagFilter tags={["design", "react"]} value="react" onChange={() => {}} />);
    await user.tab();
    const trigger = document.activeElement as HTMLElement;
    if (trigger.tagName === "SELECT") {
      expect((trigger as HTMLSelectElement).value).toBe("react");
      return;
    }
    await user.keyboard("{ArrowDown}");
    const selected = within(screen.getByRole("listbox")).getByRole("option", { name: /react/ });
    expect(selected.getAttribute("aria-selected")).toBe("true");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

describe("finding 4: buttons have names", () => {
  it("the favorite button says what it does and whether it's on", () => {
    render(<MemoryRouter><AuthProvider><FavoriteButton article={makeArticle({ favoritesCount: 3 })} /></AuthProvider></MemoryRouter>);
    const button = screen.getByRole("button", { name: /favou?rite/i });
    expect(button).toHaveAttribute("aria-pressed");
  });
});

describe("finding 5: form errors are tied to their fields", () => {
  it("marks the field invalid and reads the error with it", async () => {
    vi.spyOn(api, "createArticle").mockRejectedValue(new ApiError(422, { title: ["can't be blank"] }));
    const user = userEvent.setup();
    render(<MemoryRouter><AuthProvider><EditorPage /></AuthProvider></MemoryRouter>);
    await user.click(screen.getByRole("button", { name: /publish/i }));
    const title = await screen.findByRole("textbox", { name: /title/i });
    expect(title).toHaveAttribute("aria-invalid", "true");
    expect(title).toHaveAccessibleDescription(/can't be blank/i);
  });
});

describe("finding 6: status messages", () => {
  it("announces the confirmation through a live region that exists before the message", async () => {
    const { container, rerender } = render(<Toast message={null} />);
    const region = container.querySelector("[aria-live], [role=status], [role=alert], output");
    expect(region).not.toBeNull();
    rerender(<Toast message="Article published" />);
    expect(region!.textContent).toMatch(/article published/i);
  });
});

describe("axe-core", () => {
  it("finds no violations in the components, open and closed", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <MemoryRouter>
        <AuthProvider>
          <main>
            <h1>Article</h1>
            <FavoriteButton article={makeArticle({ favoritesCount: 2 })} />
            <ReadMore text={"Long text that needs collapsing. ".repeat(20)} limit={50} />
            <TagFilter tags={["design", "react"]} value={null} onChange={() => {}} />
            <DialogHarness />
            <Toast message={null} />
          </main>
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await violations(container)).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Delete Article" }));
    await act(async () => {});
    expect(await violations(container)).toEqual([]);
  });
});
