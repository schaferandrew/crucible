// Hidden acceptance tests for accessibility-audit-fixes (formerly CODE-15). Never copied into the model's workspace.
// The grader runs this file from apps/web (test/hidden) in a fresh copy of the seeded repo that takes
// only the model's apps/web/src.
//
// Tests behavior, not markup: native elements (<dialog>, <select>, <button>) and ARIA-pattern widgets
// both pass when they behave correctly for keyboard and screen reader users. Every test needs the fix
// to even set up, so none of them pass on the seeded repo. axe-core runs inside the finding tests
// (never as a free standalone test: axe passes the seeded repo, whose problems are behavior and
// missing roles, not markup it can see).
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

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const LIVE = "[aria-live], [role=status], [role=alert], [role=log], output";

beforeAll(() => {
  // jsdom has <dialog> but not showModal/close. Stand in for what a browser does with a modal <dialog>:
  // focus moves in, Tab stays inside, Escape fires `cancel` and closes, close() hands focus back.
  // A <dialog> opened any other way (no showModal) gets none of this, as in a browser.
  const proto = HTMLDialogElement.prototype as HTMLDialogElement & { showModal?: () => void };
  if (proto.showModal) return;
  const modals: HTMLDialogElement[] = [];
  const opener = new WeakMap<HTMLDialogElement, Element | null>();
  const live = () => modals.filter((d) => d.isConnected && d.hasAttribute("open"));
  const inside = (d: HTMLDialogElement) => Array.from(d.querySelectorAll<HTMLElement>(FOCUSABLE));
  proto.showModal = function (this: HTMLDialogElement) {
    if (this.hasAttribute("open")) {
      if (modals.includes(this)) return;
      throw new DOMException("already open", "InvalidStateError");
    }
    opener.set(this, document.activeElement);
    this.setAttribute("open", "");
    modals.push(this);
    (inside(this)[0] ?? this).focus();
  };
  proto.show = function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
  proto.close = function (this: HTMLDialogElement) {
    if (!this.hasAttribute("open")) return;
    this.removeAttribute("open");
    const at = modals.indexOf(this);
    if (at >= 0) modals.splice(at, 1);
    this.dispatchEvent(new Event("close"));
    const back = opener.get(this);
    if (back instanceof HTMLElement && back.isConnected) back.focus();
  };
  document.addEventListener("keydown", (event) => {
    const top = live().at(-1);
    if (!top) return;
    if (event.key === "Escape") {
      const cancel = new Event("cancel", { cancelable: true });
      top.dispatchEvent(cancel);
      if (!cancel.defaultPrevented) top.close();
    } else if (event.key === "Tab") {
      const items = inside(top);
      const first = items[0], last = items[items.length - 1];
      const at = document.activeElement as HTMLElement;
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (at === first || !top.contains(at))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (at === last || !top.contains(at))) { event.preventDefault(); first.focus(); }
    }
  });
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

async function openDialog(onConfirm?: () => void) {
  const user = userEvent.setup();
  const view = render(<DialogHarness onConfirm={onConfirm} />);
  const trigger = screen.getByRole("button", { name: "Delete Article" });
  await user.click(trigger);
  const dialog = screen.getByRole("dialog", { name: /delete this article/i });
  return { user, trigger, dialog, container: view.container };
}

describe("finding 1: the delete confirmation", () => {
  it("is announced as a named dialog and takes focus", async () => {
    const { dialog } = await openDialog();
    expect(dialog.tagName === "DIALOG" || dialog.getAttribute("aria-modal") === "true").toBe(true);
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("keeps Tab and Shift+Tab inside the dialog", async () => {
    const { user, dialog } = await openDialog();
    for (let i = 0; i < 6; i++) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    for (let i = 0; i < 6; i++) {
      await user.tab({ shift: true });
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it("can reach both buttons by Tab", async () => {
    const { user, dialog } = await openDialog();
    const seen = new Set<Element | null>();
    for (let i = 0; i < 4; i++) {
      seen.add(document.activeElement);
      await user.tab();
    }
    expect(seen.has(within(dialog).getByRole("button", { name: /cancel/i }))).toBe(true);
    expect(seen.has(within(dialog).getByRole("button", { name: /delete/i }))).toBe(true);
  });

  it("deletes from the keyboard", async () => {
    const onConfirm = vi.fn();
    const { user, dialog } = await openDialog(onConfirm);
    within(dialog).getByRole("button", { name: /delete/i }).focus();
    await user.keyboard("{Enter}");
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("cancels from the keyboard", async () => {
    const onConfirm = vi.fn();
    const { user, dialog } = await openDialog(onConfirm);
    within(dialog).getByRole("button", { name: /cancel/i }).focus();
    await user.keyboard(" ");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("closes on Escape without deleting, and returns focus to what opened it", async () => {
    const onConfirm = vi.fn();
    const { user, trigger } = await openDialog(onConfirm);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(trigger);
  });

  it("returns focus after Cancel too", async () => {
    const { user, trigger, dialog } = await openDialog();
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));
    expect(document.activeElement).toBe(trigger);
  });

  it("can be opened again after it closed", async () => {
    const { user, trigger } = await openDialog();
    await user.keyboard("{Escape}");
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: /delete this article/i });
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.tab();
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("has no axe violations while open", async () => {
    const { container } = await openDialog();
    await act(async () => {});
    expect(await violations(container)).toEqual([]);
  });
});

describe("finding 2: Read more", () => {
  const long = "Opening paragraph that sets the scene. ".repeat(6) + "The revealed ending only appears after expanding.";
  const expandedOf = (control: HTMLElement) =>
    control.getAttribute("aria-expanded") ?? (control.closest("details")?.open ? "true" : "false");

  async function focusControl(limit = 60) {
    const user = userEvent.setup();
    const view = render(<ReadMore text={long} limit={limit} />);
    await user.tab();
    const control = document.activeElement as HTMLElement;
    expect(control).not.toBe(document.body);
    expect(control.textContent).toMatch(/read more/i);
    return { user, control, container: view.container };
  }

  it("is a keyboard-reachable control that reports its state", async () => {
    const { user, control } = await focusControl();
    expect(expandedOf(control)).toBe("false");
    await user.keyboard("{Enter}");
    expect(screen.getByText(/revealed ending/i)).toBeInTheDocument();
    expect(expandedOf(control)).toBe("true");
  });

  it("opens with Space too", async () => {
    const { user, control } = await focusControl();
    await user.keyboard(" ");
    expect(screen.getByText(/revealed ending/i)).toBeInTheDocument();
    expect(expandedOf(control)).toBe("true");
  });

  it("puts the revealed text where a screen reader user will hear it", async () => {
    const { user, control } = await focusControl();
    await user.keyboard("{Enter}");
    const revealed = screen.getByText(/revealed ending/i);
    const focusMovedToIt = revealed.contains(document.activeElement) || (document.activeElement as HTMLElement).contains(revealed);
    const controlled = control.getAttribute("aria-controls");
    const controlsIt = Boolean(controlled && document.getElementById(controlled)?.contains(revealed));
    const live = revealed.closest("[aria-live], [role=status], [role=log]");
    const disclosure = Boolean(control.closest("details")?.contains(revealed));
    expect(focusMovedToIt || controlsIt || Boolean(live) || disclosure).toBe(true);
  });

  it("reports the collapsed state again when closed", async () => {
    const { user, control } = await focusControl();
    await user.keyboard("{Enter}");
    const now = document.activeElement as HTMLElement;
    await user.keyboard("{Enter}");
    expect(expandedOf(now)).toBe("false");
    if (!control.closest("details")) expect(screen.queryByText(/revealed ending/i)).toBeNull();
  });

  it("keeps keyboard focus after revealing", async () => {
    const { user } = await focusControl();
    await user.keyboard("{Enter}");
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toBeTruthy();
  });

  it("has no axe violations, collapsed and expanded", async () => {
    const { user, container } = await focusControl();
    expect(await violations(container)).toEqual([]);
    await user.keyboard("{Enter}");
    expect(await violations(container)).toEqual([]);
  });
});

describe("finding 3: the tag filter", () => {
  const popupOf = () => screen.queryByRole("listbox") ?? screen.queryByRole("menu");
  const itemsOf = (popup: HTMLElement) => within(popup).getAllByRole(/^(option|menuitem|menuitemradio)$/);

  async function focusTrigger(value: string | null = null, onChange: (t: string | null) => void = () => {}, tags = ["design", "react", "rust"]) {
    const user = userEvent.setup();
    const view = render(<TagFilter tags={tags} value={value} onChange={onChange} />);
    await user.tab();
    const trigger = document.activeElement as HTMLElement;
    expect(trigger).not.toBe(document.body);
    return { user, trigger, container: view.container };
  }

  it("can be used entirely from the keyboard", async () => {
    const onChange = vi.fn();
    const { user, trigger } = await focusTrigger(null, onChange);
    if (trigger.tagName === "SELECT") {
      await user.selectOptions(trigger, "react");
      expect(onChange).toHaveBeenCalledWith("react");
      return;
    }
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    await user.keyboard("{ArrowDown}");
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(itemsOf(popupOf()!).length).toBeGreaterThanOrEqual(3);
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalled();
    expect(typeof onChange.mock.calls[0][0] === "string" || onChange.mock.calls[0][0] === null).toBe(true);
  });

  it("closes on Escape with focus back on the trigger, and marks the selection", async () => {
    const { user, trigger } = await focusTrigger("react", () => {}, ["design", "react"]);
    if (trigger.tagName === "SELECT") {
      expect((trigger as HTMLSelectElement).value).toBe("react");
      expect(within(trigger).getByRole("option", { name: "react" })).toHaveProperty("selected", true);
      return;
    }
    await user.keyboard("{ArrowDown}");
    const selected = itemsOf(popupOf()!).find((o) => /react/.test(o.textContent ?? ""))!;
    expect(selected.getAttribute("aria-selected") ?? selected.getAttribute("aria-checked")).toBe("true");
    await user.keyboard("{Escape}");
    expect(popupOf()).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("is named, so a screen reader says what it filters", async () => {
    const { trigger } = await focusTrigger();
    expect(trigger).toHaveAccessibleName(/tag/i);
  });

  it("lists every tag and a way back to all of them", async () => {
    const { user, trigger } = await focusTrigger();
    if (trigger.tagName === "SELECT") {
      const names = within(trigger).getAllByRole("option").map((o) => o.textContent);
      expect(names).toEqual(expect.arrayContaining(["design", "react", "rust"]));
      expect(names.some((n) => /all/i.test(n ?? ""))).toBe(true);
      return;
    }
    await user.keyboard("{ArrowDown}");
    const names = itemsOf(popupOf()!).map((o) => o.textContent ?? "");
    expect(names).toHaveLength(4);
    expect(names.some((n) => /all/i.test(n))).toBe(true);
  });

  it("clears the filter when All tags is chosen", async () => {
    const onChange = vi.fn();
    const { user, trigger } = await focusTrigger("react", onChange);
    if (trigger.tagName === "SELECT") {
      const all = within(trigger).getAllByRole("option").find((o) => /all/i.test(o.textContent ?? ""))!;
      await user.selectOptions(trigger, all);
    } else {
      await user.keyboard("{ArrowDown}");
      await user.click(itemsOf(popupOf()!).find((o) => /all/i.test(o.textContent ?? ""))!);
    }
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("shows the current tag on the control itself", async () => {
    const { trigger } = await focusTrigger("rust");
    const shown = trigger.tagName === "SELECT"
      ? (trigger as HTMLSelectElement).selectedOptions[0]?.textContent
      : trigger.textContent;
    expect(shown).toMatch(/rust/);
  });

  it("has no axe violations, closed and open", async () => {
    const { user, trigger, container } = await focusTrigger("react");
    expect(await violations(container)).toEqual([]);
    if (trigger.tagName !== "SELECT") {
      await user.keyboard("{ArrowDown}");
      expect(await violations(container)).toEqual([]);
    }
  });
});

describe("finding 4: buttons have names", () => {
  const view = (article = makeArticle({ favoritesCount: 3 })) =>
    render(<MemoryRouter><AuthProvider><FavoriteButton article={article} /></AuthProvider></MemoryRouter>);

  it("the favorite button says what it does", () => {
    view();
    expect(screen.getByRole("button", { name: /favou?rite/i })).toBeInTheDocument();
  });

  it("reports that it's off", () => {
    view(makeArticle({ favorited: false, favoritesCount: 3 }));
    expect(screen.getByRole("button", { name: /favou?rite/i })).toHaveAttribute("aria-pressed", "false");
  });

  it("reports that it's on", () => {
    view(makeArticle({ favorited: true, favoritesCount: 3 }));
    expect(screen.getByRole("button", { name: /favou?rite/i })).toHaveAttribute("aria-pressed", "true");
  });

  it("still tells a screen reader user the count", () => {
    view();
    expect(screen.getByRole("button", { name: /favou?rite/i })).toHaveAccessibleName(/3/);
  });

  it("changes its state when toggled, and keeps its name", async () => {
    localStorage.setItem("conduit.jwt", "token");
    vi.spyOn(api, "currentUser").mockResolvedValue({ email: "j@x.com", token: "token", username: "jane", bio: null, image: null });
    vi.spyOn(api, "favorite").mockResolvedValue(makeArticle({ favorited: true, favoritesCount: 4 }));
    const user = userEvent.setup();
    view();
    const button = screen.getByRole("button", { name: /favou?rite/i });
    await vi.waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    expect(await screen.findByRole("button", { name: /favou?rite/i, pressed: true })).toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    const { container } = view();
    expect(screen.getByRole("button", { name: /favou?rite/i })).toBeInTheDocument();
    expect(await violations(container)).toEqual([]);
  });
});

describe("finding 5: form errors are tied to their fields", () => {
  async function submitWith(errors: Record<string, string[]>) {
    vi.spyOn(api, "createArticle").mockRejectedValue(new ApiError(422, errors));
    const user = userEvent.setup();
    const view = render(<MemoryRouter><AuthProvider><EditorPage /></AuthProvider></MemoryRouter>);
    await user.click(screen.getByRole("button", { name: /publish/i }));
    await screen.findAllByText(new RegExp(Object.values(errors)[0][0]));
    return view;
  }
  const title = () => screen.getByRole("textbox", { name: /title/i });
  const description = () => screen.getByRole("textbox", { name: /about/i });
  const body = () => screen.getByRole("textbox", { name: /write your article/i });

  it("marks the title invalid and reads the error with it", async () => {
    await submitWith({ title: ["can't be blank"] });
    expect(title()).toHaveAttribute("aria-invalid", "true");
    expect(title()).toHaveAccessibleDescription(/can't be blank/i);
  });

  it("does the same for the description", async () => {
    await submitWith({ description: ["is too long"] });
    expect(description()).toHaveAttribute("aria-invalid", "true");
    expect(description()).toHaveAccessibleDescription(/is too long/i);
  });

  it("does the same for the body", async () => {
    await submitWith({ body: ["can't be blank"] });
    expect(body()).toHaveAttribute("aria-invalid", "true");
    expect(body()).toHaveAccessibleDescription(/can't be blank/i);
  });

  it("leaves the fields without an error alone", async () => {
    await submitWith({ title: ["can't be blank"] });
    expect(title()).toHaveAttribute("aria-invalid", "true");
    expect(description()).not.toHaveAttribute("aria-invalid", "true");
    expect(body()).not.toHaveAttribute("aria-invalid", "true");
    expect(description()).not.toHaveAccessibleDescription(/blank/i);
  });

  it("reads every message when a field has several", async () => {
    await submitWith({ title: ["can't be blank", "is too short"] });
    expect(title()).toHaveAccessibleDescription(/can't be blank/i);
    expect(title()).toHaveAccessibleDescription(/is too short/i);
  });

  it("has no axe violations with errors showing", async () => {
    const { container } = await submitWith({ title: ["can't be blank"], body: ["can't be blank"] });
    expect(title()).toHaveAttribute("aria-invalid", "true");
    expect(await violations(container)).toEqual([]);
  });
});

describe("finding 6: status messages", () => {
  it("announces the confirmation through a live region that exists before the message", async () => {
    const { container, rerender } = render(<Toast message={null} />);
    const region = container.querySelector(LIVE);
    expect(region).not.toBeNull();
    rerender(<Toast message="Article published" />);
    expect(region!.textContent).toMatch(/article published/i);
  });

  it("announces a later message in the same region", async () => {
    const { container, rerender } = render(<Toast message={null} />);
    const region = container.querySelector(LIVE);
    expect(region).not.toBeNull();
    rerender(<Toast message="Article published" />);
    rerender(<Toast message="Article updated" />);
    expect(container.querySelector(LIVE)).toBe(region);
    expect(region!.textContent).toMatch(/article updated/i);
  });

  it("keeps the live region when the message fades", async () => {
    vi.useFakeTimers();
    try {
      const { container, rerender } = render(<Toast message={null} />);
      const region = container.querySelector(LIVE);
      expect(region).not.toBeNull();
      rerender(<Toast message="Article published" />);
      expect(region!.textContent).toMatch(/article published/i);
      await act(async () => { vi.advanceTimersByTime(6000); });
      expect(region!.isConnected).toBe(true);
      expect(region!.textContent).toBe("");
    } finally {
      vi.useRealTimers();
    }
  });

  it("puts the editor's 'Article published' into a region that was already there", async () => {
    vi.spyOn(api, "createArticle").mockResolvedValue(makeArticle());
    const user = userEvent.setup();
    const { container } = render(<MemoryRouter><AuthProvider><EditorPage /></AuthProvider></MemoryRouter>);
    const before = Array.from(container.querySelectorAll(LIVE));
    expect(before.length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: /publish/i }));
    const holder = await screen.findByText(/article published/i);
    expect(before.some((region) => region.contains(holder))).toBe(true);
  });
});
