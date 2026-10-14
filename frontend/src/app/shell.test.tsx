import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vite-plus/test";
import { healthReply, problem, stubApi } from "../test/api";
import { prefersDark } from "../test/media";
import { routes } from "./router";

function renderApp(path = "/") {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
}

describe("app shell", () => {
  it("renders the top bar, the navigation and, without a key, the connect screen", () => {
    renderApp();

    expect(screen.getByRole("banner")).toHaveTextContent("CrawlerAI");
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("main")).toContainElement(
      screen.getByRole("heading", { level: 1, name: "Connect" }),
    );
  });

  it("asks /healthz without a key and shows the Labeling entry when the API reports eval_ui", async () => {
    const calls = stubApi({ "GET /healthz": () => healthReply(true) });
    renderApp();

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(await within(nav).findByRole("link", { name: "Labeling" })).toHaveAttribute(
      "href",
      "/labeling",
    );
    expect(calls).toEqual([
      { method: "GET", path: "/healthz", query: "", authorization: null, body: null },
    ]);
  });

  it("hides the Labeling entry when the API reports eval_ui off", async () => {
    const calls = stubApi({ "GET /healthz": () => healthReply(false) });
    renderApp();

    await waitFor(() => {
      expect(calls).toHaveLength(1);
    });
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Overview", "Scrape", "Schemas", "Records", "Sites", "Jobs"]);
  });

  it("hides the Labeling entry when /healthz fails", async () => {
    const calls = stubApi({
      "GET /healthz": () => problem(503, { title: "Service Unavailable" }),
    });
    renderApp();

    await waitFor(() => {
      expect(calls).toHaveLength(1);
    });
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("link", { name: "Labeling" })).toBeNull();
  });

  it("marks the entry of the current section as the current page, on its nested routes too", async () => {
    stubApi({
      "GET /healthz": () => healthReply(true),
      "GET /v1/eval/pages/page-1": () => problem(404, { title: "Not Found" }),
    });
    renderApp("/labeling/page-1");
    // The labeling routes need a key (SPEC-03 §4.10): /connect first, then back.
    await userEvent.type(screen.getByLabelText(/API key/), "ck_first");
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));

    // The labeling route renders once its page has answered.
    await screen.findByText("No dev eval page has this id.");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    const labeling = await within(nav).findByRole("link", { name: "Labeling" });
    expect(labeling).toHaveAttribute("aria-current", "page");
    expect(
      within(nav)
        .getAllByRole("link")
        .filter((link) => link.getAttribute("aria-current") === "page"),
    ).toEqual([labeling]);
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
