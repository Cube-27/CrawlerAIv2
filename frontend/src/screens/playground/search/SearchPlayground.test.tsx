import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import { problem, stubApi } from "../../../test/api";
import {
  closeOptions,
  fill,
  openOptions,
  openPlayground,
  posted,
  toggleFormats,
} from "../../../test/playground";

// `fetch` answers `POST /v1/search` with the shape of D-1442.

const JOB_ID = "0192a000-0000-7000-8000-0000000000d1";

const RESULT = {
  query: "kettles",
  results: [
    { position: 1, url: "https://docs.test/a", title: "Kettle guide", snippet: "How to descale" },
    { position: 2, url: "https://docs.test/b", title: "", snippet: "" },
  ],
  job_id: JOB_ID,
  skipped: 1,
};

async function search() {
  await userEvent.click(screen.getByRole("button", { name: "Search" }));
}

describe("search playground", () => {
  it("is a mode tab under Web and a sidebar entry at /search", async () => {
    stubApi({});
    await openPlayground("/search");

    const web = screen.getByRole("tablist", { name: "Web" });
    expect(within(web).getByRole("tab", { name: "Search" })).toHaveAttribute("href", "/search");
    expect(
      within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", {
        name: "Search",
      }),
    ).toHaveAttribute("href", "/search");
  });

  it("posts the query and shows the results in order, with a link to the scrape of them", async () => {
    const calls = stubApi({ "POST /v1/search": () => Response.json(RESULT) });
    await openPlayground("/search");
    await fill(screen.getByRole("textbox", { name: "Query" }), "  kettles ");
    const options = await openOptions();
    await fill(options.getByRole("textbox", { name: "Result limit" }), "5");
    await userEvent.click(options.getByRole("switch", { name: "Scrape results" }));
    await closeOptions();
    await toggleFormats("Links");

    await search();

    expect(await screen.findByRole("link", { name: "Kettle guide" })).toHaveAttribute(
      "href",
      "https://docs.test/a",
    );
    expect(screen.getByText("How to descale")).toBeInTheDocument();
    expect(screen.getByText(/1 the API may not fetch/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the scrape of the results" })).toHaveAttribute(
      "href",
      `/batch?job=${JOB_ID}`,
    );
    expect(posted(calls)).toEqual({
      query: "kettles",
      limit: 5,
      scrape: { formats: ["markdown", "links"] },
    });
  });

  it("sends nothing for an empty query", async () => {
    const calls = stubApi({ "POST /v1/search": () => Response.json(RESULT) });
    await openPlayground("/search");

    await search();

    expect(await screen.findByText("Enter what to search for.")).toBeInTheDocument();
    expect(calls.filter(({ method }) => method === "POST")).toEqual([]);
  });

  it("shows the problem when no provider is configured", async () => {
    stubApi({
      "POST /v1/search": () =>
        problem(503, {
          type: "search_unavailable",
          title: "Search unavailable",
          detail: "No provider",
        }),
    });
    await openPlayground("/search");
    await fill(screen.getByRole("textbox", { name: "Query" }), "kettles");

    await search();

    expect(await screen.findByText("Search unavailable")).toBeInTheDocument();
  });
});
