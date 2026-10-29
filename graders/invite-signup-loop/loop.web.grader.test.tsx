// Hidden acceptance tests for invite-signup-loop (formerly CODE-14), web side. Never copied into the model's workspace.
// The judge copies this file to apps/web/test/hidden/ in a scratch copy and runs:
//   npx vitest run test/hidden    (from apps/web)
// It renders the real App for each kind of user and records every navigation, so a loop (or a
// redirect to the wrong place) fails regardless of how the fix is structured.
// Legal's requirements are the authority (docs/legal-contributor-terms.md): whoever has accepted the
// terms can reach the editor, whoever hasn't can't, and a profile is never required.
import type { User } from "@conduit/shared";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../../src/App";
import { api } from "../../src/api/client";
import { AuthProvider } from "../../src/auth/AuthContext";

const base: User = {
  email: "x@example.com", token: "token", username: "x", bio: null, image: null,
  accountState: "active", onboardingComplete: false, termsAcceptedAt: null,
};
const TERMS = "2026-10-20T00:00:00.000Z";
const USERS: Record<string, User> = {
  newSignup: { ...base },
  onboarded: { ...base, onboardingComplete: true, termsAcceptedAt: "2026-10-01T00:00:00.000Z" },
  // rosa and tomek: accepted their invites, so the terms are recorded, but never saw onboarding
  invitedStuck: { ...base, accountState: "invited", termsAcceptedAt: TERMS },
  // signed up with an invited address: has an account and a password, but hasn't accepted the terms
  invitedNoTerms: { ...base, accountState: "invited" },
};

function Probe({ seen }: { seen: string[] }) {
  const location = useLocation();
  if (seen[seen.length - 1] !== location.pathname) seen.push(location.pathname);
  return null;
}

async function visit(path: string, user: User | null, setup: () => void = () => {}) {
  vi.restoreAllMocks();
  localStorage.clear();
  if (user) localStorage.setItem("conduit.jwt", user.token);
  vi.spyOn(api, "currentUser").mockResolvedValue(user as User);
  for (const name of ["tags", "articles", "feed", "article", "comments"] as const) {
    vi.spyOn(api, name).mockResolvedValue((name === "tags" ? [] : name === "comments" ? [] : { articles: [], articlesCount: 0 }) as never);
  }
  setup();
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  const seen: string[] = [];
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
        <Probe seen={seen} />
      </AuthProvider>
    </MemoryRouter>,
  );
  // Let auth resolve and every redirect run; a loop keeps adding entries the whole time. A loop is
  // reported by unmounting the app and failing at once: left mounted it would starve the later tests.
  const settle = async () => {
    await new Promise((r) => setTimeout(r, 400));
    const count = seen.length;
    await new Promise((r) => setTimeout(r, 300));
    const looped = errors.mock.calls.some((c) => /Maximum update depth|Too many re-renders/.test(String(c[0])));
    if (looped || seen.length !== count) {
      view.unmount();
      throw new Error(`redirect loop: ${seen.slice(0, 6).join(" -> ")} ...`);
    }
  };
  await settle();
  return { seen, final: () => seen[seen.length - 1], view, settle };
}

describe("accounts that accepted an invite and are stuck today", () => {
  it("can reach the editor without a loop", async () => {
    const r = await visit("/editor", USERS.invitedStuck);
    expect(r.final()).toBe("/editor");
    expect(r.seen.length).toBeLessThanOrEqual(3);
  });

  it("are taken to the editor from the welcome screen too", async () => {
    const r = await visit("/welcome", USERS.invitedStuck);
    expect(r.final()).toBe("/editor");
    expect(r.seen.length).toBeLessThanOrEqual(3);
  });

  it("aren't asked to fill in a profile first", async () => {
    const r = await visit("/editor", USERS.invitedStuck);
    expect(r.final()).toBe("/editor");
    expect(r.seen).not.toContain("/welcome");
  });
});

describe("invited contributors who haven't accepted the terms", () => {
  it("can't reach the editor, and aren't looped around", async () => {
    const r = await visit("/editor", USERS.invitedNoTerms);
    expect(r.final()).not.toBe("/editor");
  });

  it("are asked for the terms and not for a bio", async () => {
    const r = await visit("/editor", USERS.invitedNoTerms);
    await waitFor(() => expect(r.view.getByRole("checkbox")).toBeInTheDocument());
    expect(r.view.queryByRole("textbox", { name: /bio/i })).toBeNull();
  });

  it("stay on the welcome screen when they open it", async () => {
    const r = await visit("/welcome", USERS.invitedNoTerms);
    expect(r.final()).toBe("/welcome");
    expect(r.view.getByRole("checkbox")).toBeInTheDocument();
  });

  it("reach the editor once they accept the terms", async () => {
    const accepted: User = { ...USERS.invitedNoTerms, onboardingComplete: true, termsAcceptedAt: TERMS };
    let complete!: ReturnType<typeof vi.spyOn>;
    const r = await visit("/editor", USERS.invitedNoTerms, () => {
      complete = vi.spyOn(api, "completeOnboarding").mockResolvedValue(accepted);
    });
    await waitFor(() => expect(r.view.getByRole("checkbox")).toBeInTheDocument());
    fireEvent.click(r.view.getByRole("checkbox"));
    fireEvent.click(r.view.getByRole("button", { name: /start writing/i }));
    await waitFor(() => expect(complete).toHaveBeenCalledTimes(1));
    await r.settle();
    expect(r.final()).toBe("/editor");
  });
});

describe("accepting an invite", () => {
  it("lands in the editor with no loop", async () => {
    const accepted: User = { ...USERS.invitedStuck, username: "rosa", token: "fresh" };
    let accept!: ReturnType<typeof vi.spyOn>;
    const r = await visit("/invite/abc123", null, () => {
      vi.spyOn(api, "invite").mockResolvedValue({ token: "abc123", email: "rosa@example.com", invitedBy: "grace", acceptedAt: null });
      accept = vi.spyOn(api, "acceptInvite").mockResolvedValue(accepted);
    });
    await waitFor(() => expect(r.view.getByRole("checkbox")).toBeInTheDocument());
    fireEvent.change(r.view.getByLabelText("Username"), { target: { value: "rosa" } });
    fireEvent.change(r.view.getByLabelText("Password"), { target: { value: "password123" } });
    fireEvent.click(r.view.getByRole("checkbox"));
    fireEvent.click(r.view.getByRole("button", { name: /accept invite/i }));
    await waitFor(() => expect(accept).toHaveBeenCalledTimes(1));
    await r.settle();
    expect(r.final()).toBe("/editor");
    expect(r.seen.length).toBeLessThanOrEqual(3);
  });
});

describe("everyone else is unchanged", () => {
  it("a new sign-up is sent to onboarding and stays there, with a bio and the terms (next to an invited contributor)", async () => {
    const invited = await visit("/editor", USERS.invitedStuck);
    expect(invited.final()).toBe("/editor");
    invited.view.unmount();
    const r = await visit("/editor", USERS.newSignup);
    expect(r.final()).toBe("/welcome");
    expect(r.view.getByRole("textbox", { name: /bio/i })).toBeInTheDocument();
    expect(r.view.getByRole("checkbox")).toBeInTheDocument();
  });

  it("a new sign-up reaches the editor after onboarding (next to an invited contributor)", async () => {
    const invited = await visit("/welcome", USERS.invitedStuck);
    expect(invited.final()).toBe("/editor");
    invited.view.unmount();
    const done: User = { ...USERS.newSignup, bio: "Hello", onboardingComplete: true, termsAcceptedAt: TERMS };
    let complete!: ReturnType<typeof vi.spyOn>;
    const r = await visit("/editor", USERS.newSignup, () => {
      complete = vi.spyOn(api, "completeOnboarding").mockResolvedValue(done);
    });
    await waitFor(() => expect(r.view.getByRole("checkbox")).toBeInTheDocument());
    fireEvent.change(r.view.getByRole("textbox", { name: /bio/i }), { target: { value: "Hello" } });
    fireEvent.click(r.view.getByRole("checkbox"));
    fireEvent.click(r.view.getByRole("button", { name: /start writing/i }));
    await waitFor(() => expect(complete).toHaveBeenCalledWith("Hello"));
    await r.settle();
    expect(r.final()).toBe("/editor");
  });

  it("an onboarded user can write, and is sent home from the welcome screen (next to an invited contributor)", async () => {
    const invited = await visit("/editor", USERS.invitedStuck);
    expect(invited.final()).toBe("/editor");
    invited.view.unmount();
    const r = await visit("/editor", USERS.onboarded);
    expect(r.final()).toBe("/editor");
    const again = await visit("/welcome", USERS.onboarded);
    expect(again.final()).toBe("/");
  });

  it("signed out goes to login (next to an invited contributor)", async () => {
    const invited = await visit("/editor", USERS.invitedStuck);
    expect(invited.final()).toBe("/editor");
    invited.view.unmount();
    const r = await visit("/editor", null);
    expect(r.final()).toBe("/login");
  });
});
