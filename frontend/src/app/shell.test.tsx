import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { prefersDark } from "../test/media";
import { routes } from "./router";

function renderApp() {
  render(<RouterProvider router={createMemoryRouter(routes)} />);
}

describe("app shell", () => {
  it("renders the top bar, the navigation and the placeholder screen", () => {
    renderApp();

    expect(screen.getByRole("banner")).toHaveTextContent("CrawlerAI");
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("main")).toContainElement(
      screen.getByRole("heading", { level: 1, name: "Overview" }),
    );
  });
});

describe("theme", () => {
  it("follows prefers-color-scheme when the viewer has not chosen", () => {
    prefersDark(true);
    renderApp();

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(screen.getByRole("switch", { name: "Dark theme" })).toBeChecked();
  });

  it("uses the light theme when the system prefers light", () => {
    renderApp();

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(screen.getByRole("switch", { name: "Dark theme" })).not.toBeChecked();
  });

  it("sets data-theme on <html> and remembers the choice when toggled", async () => {
    renderApp();

    await userEvent.click(screen.getByRole("switch", { name: "Dark theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem("crawlerai.theme")).toBe("dark");

    await userEvent.click(screen.getByRole("switch", { name: "Dark theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(localStorage.getItem("crawlerai.theme")).toBe("light");
  });

  it("prefers the remembered choice over the system preference", () => {
    prefersDark(true);
    localStorage.setItem("crawlerai.theme", "light");
    renderApp();

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
  });

  it("still renders and toggles when storage is unavailable", async () => {
    prefersDark(true);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    renderApp();

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    await userEvent.click(screen.getByRole("switch", { name: "Dark theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
  });
});
