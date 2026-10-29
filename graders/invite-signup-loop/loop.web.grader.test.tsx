// Hidden acceptance tests for C14 (redirect loop), web side. Never copied into the model's workspace.
// The judge copies this file to apps/web/test/hidden/ in a scratch copy and runs:
//   npx vitest run test/hidden    (from apps/web)
// It renders the real App for each kind of user and records every navigation, so a loop (or a
// redirect to the wrong place) fails regardless of how the fix is structured.
import type { User } from "@conduit/shared";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../../src/App";
import { api } from "../../src/api/client";
import { AuthProvider } from "../../src/auth/AuthContext";

const base: User = {
  email: "x@example.com", token: "token", username: "x", bio: null, image: null,
  accountState: "active", onboardingComplete: false, termsAcceptedAt: null,
};
const USERS: Record<string, User> = {
  newSignup: { ...base },
  onboarded: { ...base, onboardingComplete: true, termsAcceptedAt: "2026-10-01T00:00:00.000Z" },
  invitedStuck: { ...base, accountState: "invited", termsAcceptedAt: "2026-10-20T00:00:00.000Z" },
  invitedNoTerms: { ...base, accountState: "invited" },
};

function Probe({ seen }: { seen: string[] }) {
  const location = useLocation();
  if (seen[seen.length - 1] !== location.pathname) seen.push(location.pathname);
  return null;
}

async function visit(path: string, user: User | null) {
  vi.restoreAllMocks();
  localStorage.clear();
  if (user) localStorage.setItem("conduit.jwt", user.token);
  vi.spyOn(api, "currentUser").mockResolvedValue(user as User);
  for (const name of ["tags", "articles", "feed", "article", "comments"] as const) {
    vi.spyOn(api, name).mockResolvedValue((name === "tags" ? [] : name === "comments" ? [] : { articles: [], articlesCount: 0 }) as never);
  }
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
  // Let auth resolve and every redirect run; a loop keeps adding entries the whole time
  await new Promise((r) => setTimeout(r, 400));
  const settled = seen.length;
  await new Promise((r) => setTimeout(r, 300));
  const loopErrors = errors.mock.calls.filter((c) => /Maximum update depth|Too many re-renders/.test(String(c[0])));
  return { seen, final: seen[seen.length - 1], stillMoving: seen.length !== settled, loopErrors, view };
}

describe("no redirect loops, everyone lands where they should", () => {
  it("a new sign-up is sent to onboarding and stays there", async () => {
    const r = await visit("/editor", USERS.newSignup);
    expect(r.loopErrors).toEqual([]);
    expect(r.stillMoving).toBe(false);
    expect(r.final).toBe("/welcome");
  });

  it("an onboarded user can write", async () => {
    const r = await visit("/editor", USERS.onboarded);
    expect(r.stillMoving).toBe(false);
    expect(r.final).toBe("/editor");
  });

  it("an invited contributor who accepted the terms lands in the editor (accounts already in this state)", async () => {
    for (const start of ["/editor", "/welcome"]) {
      const r = await visit(start, USERS.invitedStuck);
      expect(r.loopErrors).toEqual([]);
      expect(r.stillMoving).toBe(false);
      expect(r.final).toBe("/editor");
      expect(r.seen.length).toBeLessThanOrEqual(3);
    }
  });

  it("an invited contributor who hasn't accepted the terms can't write, and isn't asked for a bio", async () => {
    const r = await visit("/editor", USERS.invitedNoTerms);
    expect(r.loopErrors).toEqual([]);
    expect(r.stillMoving).toBe(false);
    expect(r.final).not.toBe("/editor");
    await waitFor(() => expect(r.view.getByRole("checkbox")).toBeInTheDocument());
    expect(r.view.queryByRole("textbox", { name: /bio/i })).toBeNull();
  });

  it("signed out goes to login", async () => {
    const r = await visit("/editor", null);
    expect(r.stillMoving).toBe(false);
    expect(r.final).toBe("/login");
  });
});
