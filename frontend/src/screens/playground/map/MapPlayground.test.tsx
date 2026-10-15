import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { MapResult } from "../../../api/jobs";
import { stubApi, type Call } from "../../../test/api";
import { jobSummary } from "../../../test/jobs";
import { fill, openOptions, openPlayground, posted } from "../../../test/playground";

// `fetch` answers `POST /v1/map` with the shape SPEC-10 §4.4 defines.

/** 25 URLs: more than one page of the table. */
const URLS = Array.from({ length: 25 }, (_, i) => `https://shop.test/items/${String(i + 1)}`);

function mapApi(result: MapResult): Call[] {
  return stubApi({ "POST /v1/map": () => Response.json(result) });
}

async function map() {
  await fill(screen.getByRole("textbox", { name: "URL" }), "shop.test");
  await userEvent.click(screen.getByRole("button", { name: "Map" }));
}

/** The URLs in the links table's rows. */
function shownUrls(grid: HTMLElement): (string | null)[] {
  return within(grid)
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getByRole("rowheader").textContent);
}

describe("map playground", () => {
  it("is a mode tab under Sites at /map, with Options and no format or schema", async () => {
    mapApi({ urls: [], sources: { sitemap: 0, links: 0 }, truncated: false });
    await openPlayground("/map");

    const sites = screen.getByRole("tablist", { name: "Sites" });
    expect(within(sites).getByRole("tab", { name: "Map" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("button", { name: "Options" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Format/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Schema/ })).not.toBeInTheDocument();
  });

  it("posts the map request SPEC-10 defines from the bar and options", async () => {
    const calls = mapApi({ urls: URLS, sources: { sitemap: 25, links: 0 }, truncated: false });
    await openPlayground("/map");
    const options = await openOptions();
    await fill(options.getByRole("textbox", { name: "Exclude" }), "https://shop.test/cart/*", true);
    await userEvent.click(options.getByRole("switch", { name: "Use links" }));
    await userEvent.click(options.getByRole("button", { name: "Advanced" }));
    await fill(options.getByRole("textbox", { name: "Page limit" }), "100");

    await map();

    await screen.findByRole("grid", { name: "Links" });
    expect(posted(calls)).toEqual({
      url: "https://shop.test",
      include: [],
      exclude: ["https://shop.test/cart/*"],
      use_sitemaps: true,
      use_links: false,
      limit: 100,
    });
  });

  it("lists the URLs found a page at a time, with where they came from and whether the list was cut", async () => {
    mapApi({ urls: URLS, sources: { sitemap: 20, links: 5 }, truncated: true });
    await openPlayground("/map");

    await map();

    const grid = await screen.findByRole("grid", { name: "Links" });
    expect(screen.getByText("25 URLs: 20 from sitemaps, 5 from links.")).toBeInTheDocument();
    expect(screen.getByText("The list is cut short.")).toBeInTheDocument();
    expect(shownUrls(grid)).toEqual(URLS.slice(0, 20));

    await userEvent.click(screen.getByRole("button", { name: /Next/ }));

    expect(shownUrls(grid)).toEqual(URLS.slice(20));
    expect(screen.getByText("Page 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Next/ })).toBeDisabled();
  });

  it("shows a map run's request read-only, and says its URLs are not kept", async () => {
    const id = "0192a000-0000-7000-8000-0000000000m1";
    stubApi({
      [`GET /v1/jobs/${id}`]: () =>
        Response.json(
          jobSummary({
            id,
            kind: "map",
            status: "completed",
            request: { url: "https://shop.test/", use_links: false, limit: 50 },
          }),
        ),
    });
    await openPlayground(`/map?job=${id}`);

    const url = screen.getByRole("textbox", { name: "URL" });
    await waitFor(() => {
      expect(url).toHaveValue("https://shop.test/");
    });
    expect(url).toBeDisabled();
    expect(screen.getByText("A map's URLs are not kept")).toBeInTheDocument();
    const options = await openOptions();
    expect(options.getByRole("switch", { name: "Use links" })).not.toBeChecked();
  });
});
