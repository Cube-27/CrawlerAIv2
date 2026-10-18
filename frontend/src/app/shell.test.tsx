import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vite-plus/test";
import { healthReply, problem, stubApi } from "../test/api";
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

  it("asks /healthz without a key and shows the Labeling entry when the API reports eval_ui", async () => {
    const calls = stubApi({ "GET /healthz": () => healthReply(true) });
    renderApp();

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(await within(nav).findByRole("link", { name: "Labeling" })).toHaveAttribute(
      "href",
      "/labeling",
    );
    expect(calls.filter((call) => call.path === "/healthz")).toEqual([
      { method: "GET", path: "/healthz", query: "", authorization: null, body: null },
    ]);
  });

  it("hides the Labeling entry when the API reports eval_ui off", async () => {
    const calls = stubApi({ "GET /healthz": () => healthReply(false) });
    renderApp();

    await waitFor(() => {
      expect(calls.filter((call) => call.path === "/healthz")).toHaveLength(1);
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
