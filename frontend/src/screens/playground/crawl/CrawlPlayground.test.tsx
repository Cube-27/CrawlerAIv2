import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { JsonValuesItem, JsonValuesPage } from "../../../api/jobs";
import { stubApi, type Call } from "../../../test/api";
import { jobSummary } from "../../../test/jobs";
import {
  openOptions,
  fill,
  openPlayground,
  optionsButton,
  pick,
  posted,
  toggleFormats,
} from "../../../test/playground";

// `fetch` answers the crawl, job, results and events endpoints with the shapes SPEC-10 §4.2, §4.5 and SPEC-14 §4.4
// define.

const JOB_ID = "0192a000-0000-7000-8000-0000000000c1";
const JOB = `/v1/jobs/${JOB_ID}`;
const SCHEMA_ID = "0192a000-0000-7000-8000-0000000000s1";

const ITEM: JsonValuesItem = {
  url: "https://shop.test/items/1",
  outcome: "extracted",
  records: [{ title: "Blue mug" }],
};

const QUIET = () =>
  new Response(new ReadableStream(), { headers: { "content-type": "text/event-stream" } });

function crawlApi(): Call[] {
  return stubApi({
    "GET /v1/schemas": () =>
      Response.json({
        items: [
          {
            id: SCHEMA_ID,
            name: "item_detail",
            version: 2,
            origin: "user",
            status: "active",
            page_kind: "detail",
            fields: { title: { type: "text" } },
          },
        ],
      }),
    "POST /v1/crawl": () => Response.json({ job_id: JOB_ID }, { status: 202 }),
    [`GET ${JOB}`]: () => Response.json(jobSummary({ id: JOB_ID, kind: "crawl" })),
    [`GET ${JOB}/request`]: () =>
      Response.json({ url: "https://shop.test/", formats: ["markdown"] }),
    [`GET ${JOB}/events`]: QUIET,
    [`GET ${JOB}/results`]: () =>
      Response.json({
        format: "json_values",
        items: [ITEM],
        next_cursor: null,
      } satisfies JsonValuesPage),
  });
}

async function typeUrl(text: string) {
  await fill(screen.getByRole("textbox", { name: "URL" }), text);
}

async function start() {
  await userEvent.click(screen.getByRole("button", { name: "Start crawl" }));
}

describe("crawl playground", () => {
  it("is a mode tab under Sites and a sidebar entry at /crawl", async () => {
    crawlApi();
    await openPlayground("/crawl");

    const sites = screen.getByRole("tablist", { name: "Sites" });
    expect(within(sites).getByRole("tab", { name: "Crawl" })).toHaveAttribute("href", "/crawl");
    expect(within(sites).getByRole("tab", { name: "Crawl" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Crawl" }),
    ).toHaveAttribute("href", "/crawl");
  });

  it("posts the crawl request SPEC-10 defines from the bar, toolbar and options, and runs it on the page", async () => {
    const calls = crawlApi();
    await openPlayground("/crawl");
    await typeUrl("shop.test/");
    await toggleFormats("Links");
    const options = await openOptions();
    await fill(
      options.getByRole("textbox", { name: "Include" }),
      "https://shop.test/items/*",
      true,
    );
    await fill(options.getByRole("textbox", { name: "Exclude" }), "https://shop.test/cart/*");
    await userEvent.click(options.getByRole("button", { name: "Add to Exclude" }));
    await userEvent.click(options.getByRole("button", { name: "Add rule" }));
    await fill(options.getByRole("textbox", { name: "Pattern 1" }), "https://shop.test/items/*");
    await pick(/Page kind 1/, "Listing");

    await start();

    expect(await screen.findByRole("grid", { name: "Pages" })).toBeInTheDocument();
    expect(await screen.findByText(ITEM.url)).toBeInTheDocument();
    expect(posted(calls)).toEqual({
      url: "https://shop.test/",
      formats: ["markdown", "links"],
      schema: null,
      page_kind_rules: [{ pattern: "https://shop.test/items/*", page_kind: "listing" }],
      include: ["https://shop.test/items/*"],
      exclude: ["https://shop.test/cart/*"],
      fetch: { method_hint: "auto" },
    });
  });

  it("asks for records alone with a schema, every rule of the schema's page kind", async () => {
    const calls = crawlApi();
    await openPlayground("/crawl");
    await typeUrl("https://shop.test/");
    await pick(/Schema/, "item_detail version 2");
    const options = await openOptions();
    await userEvent.click(options.getByRole("button", { name: "Add rule" }));
    await fill(options.getByRole("textbox", { name: "Pattern 1" }), "https://shop.test/items/*");

    await start();

    await screen.findByRole("grid", { name: "Pages" });
    expect(posted(calls)).toEqual({
      url: "https://shop.test/",
      formats: ["records"],
      schema: { id: SCHEMA_ID },
      page_kind_rules: [{ pattern: "https://shop.test/items/*", page_kind: "detail" }],
      include: [],
      exclude: [],
      fetch: { method_hint: "auto" },
    });
  });

  it("says a schema's records need a rule, opening the options, and sends nothing", async () => {
    const calls = crawlApi();
    await openPlayground("/crawl");
    await typeUrl("https://shop.test/");
    await pick(/Schema/, "item_detail version 2");

    await start();

    const options = within(await screen.findByRole("region", { name: "Options" }));
    expect(options.getByRole("alert")).toHaveTextContent(
      "A schema's records need a page-kind rule: a page no rule matches is not extracted.",
    );
    expect(calls.filter(({ method }) => method === "POST")).toEqual([]);
  });

  it("removes a glob from its tag, and marks the options only while a setting differs", async () => {
    crawlApi();
    await openPlayground("/crawl");
    const options = await openOptions();
    expect(optionsButton()).not.toHaveAccessibleDescription("Settings changed");

    await fill(options.getByRole("textbox", { name: "Include" }), "https://shop.test/a/*", true);
    expect(optionsButton()).toHaveAccessibleDescription("Settings changed");
    await userEvent.click(
      within(options.getByRole("grid", { name: "Include" })).getByRole("button", {
        name: /Remove/,
      }),
    );

    expect(options.queryByRole("grid", { name: "Include" })).not.toBeInTheDocument();
    expect(optionsButton()).not.toHaveAccessibleDescription("Settings changed");
  });

  it("opens the pages selected in its results as a batch", async () => {
    crawlApi();
    await openPlayground(`/crawl?job=${JOB_ID}`);
    await screen.findByText(ITEM.url);

    await userEvent.click(screen.getByRole("checkbox", { name: `Select ${ITEM.url}` }));
    await userEvent.click(screen.getByRole("button", { name: "Scrape as batch" }));

    expect(await screen.findByRole("textbox", { name: "URLs" })).toHaveValue(ITEM.url);
  });
});
