import type { User } from "@conduit/shared";
import { screen, waitFor } from "@testing-library/react";
import { Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { api } from "../src/api/client";
import { RequireWriter } from "../src/auth/RequireWriter";
import { renderWithProviders } from "./render";

const invited: User = {
  email: "rosa@example.com", token: "token", username: "rosa", bio: null, image: null,
  accountState: "invited", onboardingComplete: false, termsAcceptedAt: "2026-10-20T00:00:00.000Z",
};

function Where() {
  return <p>at {useLocation().pathname}</p>;
}

function renderGuard(user: User) {
  localStorage.setItem("conduit.jwt", user.token);
  vi.spyOn(api, "currentUser").mockResolvedValue(user);
  renderWithProviders(
    <Routes>
      <Route path="/editor" element={<RequireWriter><p>editor</p></RequireWriter>} />
      <Route path="*" element={<Where />} />
    </Routes>,
    "/editor",
  );
}

describe("RequireWriter", () => {
  it("lets in an invited contributor who accepted the terms, with no profile", async () => {
    renderGuard(invited);
    expect(await screen.findByText("editor")).toBeInTheDocument();
  });

  it("sends someone who hasn't accepted the terms to the welcome screen", async () => {
    renderGuard({ ...invited, termsAcceptedAt: null });
    await waitFor(() => expect(screen.getByText("at /welcome")).toBeInTheDocument());
  });
});
