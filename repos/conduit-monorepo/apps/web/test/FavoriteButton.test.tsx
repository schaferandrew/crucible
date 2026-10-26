import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../src/api/client";
import { FavoriteButton } from "../src/components/FavoriteButton";
import { makeArticle, renderWithProviders } from "./render";

function signIn() {
  localStorage.setItem("conduit.jwt", "token");
  vi.spyOn(api, "currentUser").mockResolvedValue({ email: "j@x.com", token: "token", username: "jane", bio: null, image: null });
}

describe("FavoriteButton", () => {
  it("is disabled when signed out", () => {
    renderWithProviders(<FavoriteButton article={makeArticle({ favoritesCount: 3 })} />);
    expect(screen.getByRole("button")).toBeDisabled();
    expect(screen.getByRole("button")).toHaveTextContent("3");
  });

  it("favorites and shows the server's count", async () => {
    signIn();
    vi.spyOn(api, "favorite").mockResolvedValue(makeArticle({ favorited: true, favoritesCount: 4 }));
    renderWithProviders(<FavoriteButton article={makeArticle({ favoritesCount: 3 })} />);
    const button = screen.getByRole("button");
    await vi.waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(button).toHaveTextContent("4");
  });

  it("unfavorites a favorited article", async () => {
    signIn();
    const unfavorite = vi.spyOn(api, "unfavorite").mockResolvedValue(makeArticle({ favorited: false, favoritesCount: 0 }));
    renderWithProviders(<FavoriteButton article={makeArticle({ favorited: true, favoritesCount: 1 })} />);
    const button = screen.getByRole("button");
    await vi.waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    expect(unfavorite).toHaveBeenCalledWith("an-article");
    expect(button).toHaveAttribute("aria-pressed", "false");
  });
});
