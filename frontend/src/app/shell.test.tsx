import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vite-plus/test";
import { stubApi } from "../test/api";
import { routes } from "./router";

function renderApp(path = "/") {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
}

describe("app shell", () => {
  it("renders the sidebar, the navigation and the Scrape playground at /, with no key prompt", () => {
    renderApp();

    expect(screen.getByRole("complementary", { name: "Sidebar" })).toHaveTextContent("CrawlerAI");
    expect(screen.getByRole("link", { name: "Scrape" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("main")).toContainElement(
      screen.getByRole("heading", { level: 1, name: "Playground" }),
    );
    expect(screen.queryByLabelText(/API key/)).not.toBeInTheDocument();
  });

  it("marks the entry of the current section as the current page, on its nested routes too", async () => {
    stubApi({});
    renderApp("/schemas/new");

    await screen.findByRole("heading", { level: 1, name: "New schema" });
    const nav = screen.getByRole("navigation", { name: "Main" });
    const schemas = within(nav).getByRole("link", { name: "Schemas" });
    expect(schemas).toHaveAttribute("aria-current", "page");
    expect(
      within(nav)
        .getAllByRole("link")
        .filter((link) => link.getAttribute("aria-current") === "page"),
    ).toEqual([schemas]);
  });
});

describe("theme", () => {
  it("sets data-theme on <html> and remembers the choice when toggled", async () => {
    renderApp();

    await userEvent.click(screen.getByRole("button", { name: "Dark theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem("crawlerai.theme")).toBe("dark");

    await userEvent.click(screen.getByRole("button", { name: "Dark theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(localStorage.getItem("crawlerai.theme")).toBe("light");
  });
});
