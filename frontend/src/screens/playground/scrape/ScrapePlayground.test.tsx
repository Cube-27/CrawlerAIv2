import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { RecordField, ScrapeResponse } from "../../../api/scrape";
import { problem, stubApi } from "../../../test/api";
import {
  closeOptions,
  openOptions,
  openPlayground,
  pick,
  posted,
  selectTrigger,
  toggleFormats,
} from "../../../test/playground";

// `fetch` answers POST /v1/scrape and GET /v1/schemas/{id} with the shapes SPEC-07 §4.3–4.4 define.

const SCHEMA_ID = "0192a000-0000-7000-8000-0000000000s1";

function field(overrides: Partial<RecordField>): RecordField {
  return {
    value: null,
    status: "published",
    reason: null,
    evidence: "structured",
    confidence: 0.98,
    calibrated: true,
    source_kind: "jsonld",
    locator: "jsonld:0:$.name",
    derived_by: null,
    ...overrides,
  };
}

const itemSchema = {
  id: SCHEMA_ID,
  name: "item_detail",
  origin: "user",
  fields: {
    title: { type: "text" },
    price: { type: "money" },
    brand: { type: "text" },
    tags: { type: "list", item: { type: "text" } },
  },
};

function scrapeResponse(overrides: Partial<ScrapeResponse> = {}): ScrapeResponse {
  return {
    job_id: "0192a000-0000-7000-8000-0000000000j1",
    capture_id: "0192a000-0000-7000-8000-0000000000c1",
    url: "https://store.test/items/1",
    final_url: "https://store.test/items/1?ref=final",
    fetched_at: "2026-10-13T10:00:00Z",
    outcome: "extracted",
    reason: null,
    fetch: {
      method: "browser",
      status_code: 200,
      block_class: "ok",
      adapter: null,
      attempts: [
        {
          method: "http",
          status: 200,
          block_class: "shell",
          duration_ms: 120,
          steps: [],
          error: null,
        },
        {
          method: "browser",
          status: 200,
          block_class: "ok",
          duration_ms: 2400,
          steps: [],
          error: null,
        },
      ],
    },
    usage: {
      llm_calls: 1,
      llm_tokens_in: 1200,
      llm_tokens_out: 80,
      browser_seconds: 3,
      http_requests: 2,
    },
    ...overrides,
  };
}

const withRecords = scrapeResponse({
  markdown: "# Blue mug\n\nEUR 19.90",
  records: [
    {
      id: "0192a000-0000-7000-8000-0000000000r1",
      mode: "adhoc",
      complete: false,
      confidence: 0.71,
      fields: {
        title: field({ value: "Blue mug", calibrated: false, locator: "jsonld:0:$.name" }),
        price: field({
          value: { amount: "19.90", currency: "EUR" },
          locator: "jsonld:0:$.offers.price",
        }),
        tags: field({ value: ["blue", "mug"], locator: "jsonld:0:$.keywords" }),
        brand: field({
          status: "conflict",
          reason: "disagree",
          value: null,
          evidence: null,
          confidence: null,
          source_kind: null,
          locator: null,
        }),
      },
    },
  ],
});

/** `GET /v1/schemas`: the stored schemas the form offers. */
function schemaList(): Response {
  return Response.json({ items: [{ ...itemSchema, status: "active", page_kind: "detail" }] });
}

async function openScrape() {
  await openPlayground("/");
}

async function typeUrl(url = "https://store.test/a") {
  await userEvent.type(screen.getByRole("textbox", { name: "URL" }), url);
}

/** Stubs the API with `replies`; the toolbar's schema list is always read. */
function stubScrape(replies: Parameters<typeof stubApi>[0]) {
  return stubApi({ "GET /v1/schemas": schemaList, ...replies });
}

async function fillRecordsByIdForm() {
  await typeUrl("https://store.test/items/1");
  await pick(/Schema/, "item_detail");
}

async function submit() {
  await userEvent.click(screen.getByRole("button", { name: "Scrape" }));
}

async function openTab(name: string) {
  await userEvent.click(await screen.findByRole("tab", { name }));
  return within(screen.getByRole("tabpanel", { name }));
}

describe("scrape playground: the request", () => {
  it("posts the request SPEC-07 defines: a schema asks for records, with the schema's page kind", async () => {
    const calls = stubScrape({
      "POST /v1/scrape": () => Response.json(withRecords),
      [`GET /v1/schemas/${SCHEMA_ID}`]: () => Response.json(itemSchema),
    });
    await openScrape();
    await fillRecordsByIdForm();

    await submit();

    await screen.findByRole("tab", { name: "JSON" });
    expect(calls.find(({ method }) => method === "POST")).toEqual({
      method: "POST",
      path: "/v1/scrape",
      query: "",
      authorization: null,
      body: {
        url: "https://store.test/items/1",
        formats: ["markdown", "records"],
        schema: { id: SCHEMA_ID },
        page_kind: "detail",
        fetch: { method_hint: "auto" },
      },
    });
  });

  it("sends the formats, page kind, limits and fetch method that were set, and leaves empty limits to the server", async () => {
    const calls = stubScrape({ "POST /v1/scrape": () => Response.json(scrapeResponse()) });
    await openScrape();
    await typeUrl();
    await toggleFormats("Markdown", "Links");
    const options = await openOptions();
    await pick(/Page kind/, "Listing");
    await pick(/Fetch method/, "Browser");
    await userEvent.type(options.getByRole("textbox", { name: "Max age (s)" }), "3600");
    await userEvent.type(options.getByRole("textbox", { name: "Timeout (s)" }), "90");
    await userEvent.type(options.getByRole("textbox", { name: "LLM call limit" }), "0");
    await userEvent.type(options.getByRole("textbox", { name: "Max rows" }), "60");
    await closeOptions();

    await submit();

    await screen.findByText("extracted");
    expect(posted(calls)).toEqual({
      url: "https://store.test/a",
      formats: ["links"],
      schema: null,
      page_kind: "listing",
      fetch: { method_hint: "browser", max_rows: 60 },
      max_age: 3600,
      timeout_s: 90,
      budget: { llm_calls: 0 },
    });
  });

  it("sends nothing and marks Format when no format, Metadata in JSON or schema is chosen", async () => {
    const calls = stubScrape({});
    await openScrape();
    await typeUrl();
    await toggleFormats("Markdown");

    await submit();

    expect(calls.filter(({ method }) => method === "POST")).toEqual([]);
    expect(selectTrigger(/Format/).closest("[data-invalid]")).not.toBeNull();
    expect(
      screen.getByText("Choose a format, Metadata in JSON, a schema or fields."),
    ).toBeInTheDocument();
  });
});

describe("scrape playground: records", () => {
  it("shows each record field with its value, status, confidence, evidence, source and locator", async () => {
    stubScrape({
      "POST /v1/scrape": () => Response.json(withRecords),
      [`GET /v1/schemas/${SCHEMA_ID}`]: () => Response.json(itemSchema),
    });
    await openScrape();
    await fillRecordsByIdForm();

    await submit();

    const records = await openTab("Table");
    const price = within(records.getByRole("row", { name: /price/ }));
    expect(price.getByText("19.90 EUR")).toBeInTheDocument();
    expect(price.getByText("published")).toBeInTheDocument();
    expect(price.getByText("0.98")).toBeInTheDocument();
    expect(price.getByText("Structured data")).toHaveAttribute("title", "structured");
    expect(price.getByText("JSON-LD")).toHaveAttribute("title", "jsonld");
    expect(price.getByText("jsonld:0:$.offers.price")).toBeInTheDocument();
    const title = within(records.getByRole("row", { name: /title/ }));
    expect(title.getByText("Blue mug")).toBeInTheDocument();
    // The record's one badge sits with its summary, not in a field's row.
    expect(title.queryByText("uncalibrated")).not.toBeInTheDocument();
    expect(records.getAllByText("uncalibrated")).toHaveLength(1);
    expect(records.getByText("incomplete")).toBeInTheDocument();
  });
});

/** The JSON tab's text, parsed. */
function shownJson(): unknown {
  return JSON.parse(screen.getByRole("region", { name: "Page JSON" }).textContent);
}

describe("scrape playground: JSON output", () => {
  it("opens on the JSON tab with the page's record alone: published fields in name order, money flat", async () => {
    stubScrape({
      "POST /v1/scrape": () => Response.json(withRecords),
      [`GET /v1/schemas/${SCHEMA_ID}`]: () => Response.json(itemSchema),
    });
    await openScrape();
    await fillRecordsByIdForm();

    await submit();

    expect(await screen.findByRole("tab", { name: "JSON" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(shownJson()).toEqual({
      currency: "EUR",
      price: "19.90",
      tags: ["blue", "mug"],
      title: "Blue mug",
    });
    expect(Object.keys(shownJson() as object)).toEqual(["price", "currency", "tags", "title"]);
  });
});

describe("scrape playground: formats and problems", () => {
  it("shows each returned format in its own tab", async () => {
    stubScrape({
      "POST /v1/scrape": () =>
        Response.json(
          scrapeResponse({
            markdown: "# Blue mug",
            html: "<h1>Blue mug</h1>",
            raw_html: "<html><body><h1>Blue mug</h1></body></html>",
            links: ["https://store.test/items/2"],
            metadata: {
              title: "Blue mug",
              description: "A mug",
              language: "en",
              canonical: "https://store.test/items/1",
              og: { "og:type": "product" },
              structured_data_types: ["Product", "Offer"],
            },
          }),
        ),
    });
    await openScrape();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");

    await submit();

    expect((await openTab("Markdown")).getByRole("textbox")).toHaveValue("# Blue mug");
    expect((await openTab("HTML")).getByRole("textbox")).toHaveValue("<h1>Blue mug</h1>");
    expect((await openTab("Raw HTML")).getByRole("textbox")).toHaveValue(
      "<html><body><h1>Blue mug</h1></body></html>",
    );
    expect((await openTab("Links")).getByText("https://store.test/items/2")).toBeInTheDocument();
    const metadata = await openTab("Metadata");
    expect(
      within(metadata.getByRole("row", { name: /Structured data types/ })).getByText(
        "Product, Offer",
      ),
    ).toBeInTheDocument();
    expect(
      within(metadata.getByRole("row", { name: /og:type/ })).getByText("product"),
    ).toBeInTheDocument();
    expect((await openTab("Table")).getByText("No records")).toBeInTheDocument();
  });

  it("shows a problem with its per-field errors, and the retry time on 429", async () => {
    stubScrape({
      "POST /v1/scrape": () =>
        problem(
          429,
          { type: "rate_limited", title: "Too many requests", detail: "Slow down." },
          { "Retry-After": "7" },
        ),
    });
    await openScrape();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");

    await submit();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Too many requests");
    expect(alert).toHaveTextContent("Slow down.");
    expect(alert).toHaveTextContent("Retry after 7 seconds.");
  });
});
