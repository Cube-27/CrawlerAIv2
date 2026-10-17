import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { RecordField, ScrapeResponse } from "../../../api/scrape";
import { problem, stubApi } from "../../../test/api";
import { catchDownloads } from "../../../test/downloads";
import {
  closeOptions,
  openOptions,
  openPlayground,
  optionsButton,
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
    fetch: {
      method: "browser",
      status_code: 200,
      block_class: "ok",
      attempts: [
        { method: "http", status: 200, block_class: "shell", duration_ms: 120, error: null },
        { method: "browser", status: 200, block_class: "ok", duration_ms: 2400, error: null },
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

describe("scrape playground: the shell", () => {
  it("is the app's start page, under Playground in the main navigation", async () => {
    await openScrape();

    expect(
      within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", {
        name: "Scrape",
      }),
    ).toHaveAttribute("href", "/");
  });

  it("switches modes with tabs that are links to their routes", async () => {
    await openScrape();

    const tab = within(screen.getByRole("navigation", { name: "Mode" })).getByRole("tab", {
      name: "Scrape",
    });
    expect(tab).toHaveAttribute("href", "/");
    expect(tab).toHaveAttribute("aria-selected", "true");
  });

  it("opens every setting at once in a popover from Options, with no Advanced section, and closes on Escape", async () => {
    await openScrape();
    expect(screen.queryByRole("dialog", { name: "Options" })).not.toBeInTheDocument();

    const options = await openOptions();

    expect(optionsButton()).toHaveAttribute("aria-expanded", "true");
    expect(options.getByRole("switch", { name: "Metadata in JSON" })).toBeVisible();
    expect(options.getByRole("textbox", { name: "Max age (s)" })).toBeVisible();
    expect(options.getByRole("textbox", { name: "Timeout (s)" })).toBeVisible();
    expect(options.getByRole("textbox", { name: "LLM call limit" })).toHaveAttribute(
      "placeholder",
      "Project setting",
    );
    expect(options.queryByRole("button", { name: "Advanced" })).not.toBeInTheDocument();

    await closeOptions();
    expect(optionsButton()).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps a number typed just before Escape closes the options", async () => {
    await openScrape();
    const options = await openOptions();
    await userEvent.type(options.getByRole("textbox", { name: "LLM call limit" }), "7");

    await closeOptions();

    const reopened = await openOptions();
    expect(reopened.getByRole("textbox", { name: "LLM call limit" })).toHaveValue("7");
  });

  it("marks Options exactly when a setting differs from its default, until Reset settings", async () => {
    await openScrape();
    const options = await openOptions();
    expect(optionsButton()).not.toHaveAccessibleDescription();

    await userEvent.click(options.getByRole("switch", { name: "Metadata in JSON" }));
    expect(optionsButton()).toHaveAccessibleDescription("Settings changed");

    await userEvent.click(options.getByRole("switch", { name: "Metadata in JSON" }));
    expect(optionsButton()).not.toHaveAccessibleDescription();

    await userEvent.type(options.getByRole("textbox", { name: "Timeout (s)" }), "90");
    await userEvent.tab();
    expect(optionsButton()).toHaveAccessibleDescription("Settings changed");

    await userEvent.click(options.getByRole("button", { name: "Reset settings" }));
    expect(optionsButton()).not.toHaveAccessibleDescription();
    expect(options.getByRole("textbox", { name: "Timeout (s)" })).toHaveValue("");
  });
});

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
    await closeOptions();

    await submit();

    await screen.findByText("extracted");
    expect(posted(calls)).toEqual({
      url: "https://store.test/a",
      formats: ["links"],
      schema: null,
      page_kind: "listing",
      fetch: { method_hint: "browser" },
      max_age: 3600,
      timeout_s: 90,
      budget: { llm_calls: 0 },
    });
  });

  it("asks for the metadata format with Metadata in JSON", async () => {
    const calls = stubScrape({ "POST /v1/scrape": () => Response.json(scrapeResponse()) });
    await openScrape();
    await typeUrl();
    const options = await openOptions();
    await userEvent.click(options.getByRole("switch", { name: "Metadata in JSON" }));
    await closeOptions();

    await submit();

    await screen.findByText("extracted");
    expect(posted(calls)).toMatchObject({ formats: ["markdown", "metadata"] });
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

  it("shows the latest scrape's reply when an earlier one returns after it", async () => {
    const replies: ((response: Response) => void)[] = [];
    stubScrape({
      "POST /v1/scrape": () =>
        new Promise<Response>((resolve) => {
          replies.push(resolve);
        }),
    });
    await openScrape();
    await typeUrl();
    await submit();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "x{Enter}");
    await waitFor(() => {
      expect(replies).toHaveLength(2);
    });

    replies[1]?.(Response.json(scrapeResponse()));
    await screen.findByText("extracted");
    replies[0]?.(problem(404, { type: "not_found", title: "Not found" }));

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText("extracted")).toBeInTheDocument();
  });

  it("drops the Format error once a schema or Metadata in JSON gives the scrape something to ask for", async () => {
    const calls = stubScrape({ "POST /v1/scrape": () => Response.json(scrapeResponse()) });
    await openScrape();
    await typeUrl();
    await toggleFormats("Markdown");
    await submit();
    const options = await openOptions();

    await userEvent.click(options.getByRole("switch", { name: "Metadata in JSON" }));
    await closeOptions();
    await submit();

    await screen.findByText("extracted");
    expect(posted(calls)).toMatchObject({ formats: ["metadata"] });
  });

  it("sends a URL typed without a scheme with the https:// the bar shows", async () => {
    const calls = stubScrape({ "POST /v1/scrape": () => Response.json(scrapeResponse()) });
    await openScrape();
    await typeUrl("store.test/a");

    await submit();

    await screen.findByText("extracted");
    expect(posted(calls)).toMatchObject({ url: "https://store.test/a" });
  });

  it("sends a host and port typed without a scheme with the https:// the bar shows", async () => {
    const calls = stubScrape({ "POST /v1/scrape": () => Response.json(scrapeResponse()) });
    await openScrape();
    await typeUrl("localhost:8000/a");

    await submit();

    await screen.findByText("extracted");
    expect(posted(calls)).toMatchObject({ url: "https://localhost:8000/a" });
  });

  it("sends nothing and opens the options, saying why, when a schema's records are for no page kind it can ask for", async () => {
    const listing = { ...itemSchema, status: "active", page_kind: "listing" };
    const calls = stubScrape({ "GET /v1/schemas": () => Response.json({ items: [listing] }) });
    await openScrape();
    await fillRecordsByIdForm();

    await submit();

    expect(calls.filter(({ method }) => method === "POST")).toEqual([]);
    expect(screen.getByRole("dialog", { name: "Options" })).toBeInTheDocument();
    expect(screen.getByText("Records of listing pages are not available yet.")).toBeInTheDocument();
    await userEvent.click(selectTrigger(/Page kind/));
    for (const kind of ["Detail", "Listing"]) {
      expect(await screen.findByRole("option", { name: kind })).toHaveAttribute(
        "aria-disabled",
        "true",
      );
    }
  });

  it("offers only the chosen schema's page kind", async () => {
    stubScrape({});
    await openScrape();
    await fillRecordsByIdForm();
    await openOptions();

    expect(selectTrigger(/Page kind/)).toHaveTextContent("Detail");
    await userEvent.click(selectTrigger(/Page kind/));
    expect(await screen.findByRole("option", { name: "Listing" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("drops the page kind a previous schema set when the next one has none for its records", async () => {
    const listing = {
      ...itemSchema,
      id: "0f9e8d7c-6b5a-4f3e-9d2c-1b0a9f8e7d6c",
      name: "item_listing",
      status: "active",
      page_kind: "listing",
    };
    const calls = stubScrape({
      "GET /v1/schemas": () =>
        Response.json({
          items: [{ ...itemSchema, status: "active", page_kind: "detail" }, listing],
        }),
    });
    await openScrape();
    await fillRecordsByIdForm();
    await pick(/Schema/, "item_listing");

    await submit();

    expect(calls.filter(({ method }) => method === "POST")).toEqual([]);
    expect(screen.getByRole("dialog", { name: "Options" })).toBeInTheDocument();
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
    expect(price.getByText("structured")).toBeInTheDocument();
    expect(price.getByText("jsonld")).toBeInTheDocument();
    expect(price.getByText("jsonld:0:$.offers.price")).toBeInTheDocument();
    const title = within(records.getByRole("row", { name: /title/ }));
    expect(title.getByText("Blue mug")).toBeInTheDocument();
    expect(title.getByText("uncalibrated")).toBeInTheDocument();
    expect(records.getByText("incomplete")).toBeInTheDocument();
  });

  it("renders a conflict field as an em dash with reason disagree, its status, and no value", async () => {
    stubScrape({
      "POST /v1/scrape": () => Response.json(withRecords),
      [`GET /v1/schemas/${SCHEMA_ID}`]: () => Response.json(itemSchema),
    });
    await openScrape();
    await fillRecordsByIdForm();

    await submit();

    const records = await openTab("Table");
    const brand = within(records.getByRole("row", { name: /brand/ }));
    expect(brand.getByLabelText("No value: disagree")).toHaveTextContent("—");
    expect(brand.getAllByText("conflict").length).toBeGreaterThan(0);
  });

  it("shows field values as JSON when the schema can't be read", async () => {
    stubScrape({
      "POST /v1/scrape": () => Response.json(withRecords),
      [`GET /v1/schemas/${SCHEMA_ID}`]: () =>
        problem(404, { type: "not_found", title: "Not found" }),
    });
    await openScrape();
    await fillRecordsByIdForm();

    await submit();

    const records = await openTab("Table");
    expect(
      within(records.getByRole("row", { name: /price/ })).getByText(
        '{"amount":"19.90","currency":"EUR"}',
      ),
    ).toBeInTheDocument();
    const tags = within(records.getByRole("row", { name: /tags/ }));
    expect(tags.getByText('["blue","mug"]')).toBeInTheDocument();
    expect(tags.queryByLabelText(/No value/)).not.toBeInTheDocument();
  });

  it("still shows the records when the schema request itself fails", async () => {
    stubScrape({
      "POST /v1/scrape": () => Response.json(withRecords),
      [`GET /v1/schemas/${SCHEMA_ID}`]: () => {
        throw new TypeError("network down");
      },
    });
    await openScrape();
    await fillRecordsByIdForm();

    await submit();

    const records = await openTab("Table");
    expect(within(records.getByRole("row", { name: /title/ })).getByText("Blue mug")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
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

  it("lists the tabs JSON, Table, each page format asked for, then Usage", async () => {
    stubScrape({
      "POST /v1/scrape": () =>
        Response.json(scrapeResponse({ markdown: "# Blue mug", links: ["https://store.test/b"] })),
    });
    await openScrape();
    await typeUrl();

    await submit();

    const tabs = within(await screen.findByRole("tablist", { name: "Scrape output" }));
    expect(tabs.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "JSON",
      "Table",
      "Markdown",
      "Links",
      "Usage",
    ]);
  });

  it("adds the page's metadata to the JSON with Metadata in JSON", async () => {
    const metadata = {
      title: "Blue mug",
      description: null,
      language: "en",
      canonical: null,
      og: {},
      structured_data_types: [],
    };
    stubScrape({ "POST /v1/scrape": () => Response.json(scrapeResponse({ metadata })) });
    await openScrape();
    await typeUrl();
    const options = await openOptions();
    await userEvent.click(options.getByRole("switch", { name: "Metadata in JSON" }));
    await closeOptions();

    await submit();

    await screen.findByRole("tab", { name: "JSON" });
    expect(shownJson()).toEqual({ data: [], metadata });
  });

  it("shows one uncalibrated badge exactly when a published field is uncalibrated", async () => {
    const calibrated = scrapeResponse({
      records: [
        {
          id: "0192a000-0000-7000-8000-0000000000r2",
          mode: "config",
          complete: true,
          confidence: 0.9,
          fields: {
            title: field({ value: "Blue mug" }),
            // Not published: its calibration says nothing about a shown value.
            brand: field({ status: "abstained", reason: "low_confidence", calibrated: false }),
          },
        },
      ],
    });
    const replies = [withRecords, calibrated];
    stubScrape({
      "POST /v1/scrape": () => Response.json(replies.shift()),
      [`GET /v1/schemas/${SCHEMA_ID}`]: () => Response.json(itemSchema),
    });
    await openScrape();
    await fillRecordsByIdForm();

    await submit();
    const json = await openTab("JSON");
    expect(json.getAllByText("uncalibrated")).toHaveLength(1);
    await submit();

    await waitFor(() => {
      expect(shownJson()).toEqual({ title: "Blue mug" });
    });
    expect(
      within(screen.getByRole("tabpanel", { name: "JSON" })).queryByText("uncalibrated"),
    ).toBeNull();
  });

  it("downloads the JSON as the job's file", async () => {
    const saved = catchDownloads();
    stubScrape({ "POST /v1/scrape": () => Response.json(scrapeResponse()) });
    await openScrape();
    await typeUrl();
    await submit();

    await userEvent.click(await screen.findByRole("button", { name: "Download" }));

    expect(saved.map(({ name }) => name)).toEqual([
      "job-0192a000-0000-7000-8000-0000000000j1.json",
    ]);
    expect(JSON.parse(await (saved[0]?.text ?? Promise.resolve("")))).toEqual([]);
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

  it("shows the outcome, fetch attempts and usage", async () => {
    stubScrape({
      "POST /v1/scrape": () => Response.json(scrapeResponse({ outcome: "blocked" })),
    });
    await openScrape();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");

    await submit();

    expect(await screen.findByText("blocked")).toBeInTheDocument();
    expect(screen.getByText("https://store.test/items/1?ref=final")).toBeInTheDocument();
    const usage = await openTab("Usage");
    const httpAttempt = within(usage.getByRole("row", { name: "http" }));
    expect(httpAttempt.getByText("shell")).toBeInTheDocument();
    expect(httpAttempt.getByText("120")).toBeInTheDocument();
    expect(
      within(usage.getByRole("row", { name: /LLM tokens in/ })).getByText("1200"),
    ).toBeVisible();
  });

  it("shows a page robots.txt kept from being fetched without a fetch or a final URL", async () => {
    stubScrape({
      "POST /v1/scrape": () =>
        Response.json(
          scrapeResponse({
            outcome: "blocked",
            capture_id: null,
            final_url: null,
            fetched_at: null,
            fetch: null,
          }),
        ),
    });
    await openScrape();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");

    await submit();

    expect(await screen.findByText("blocked")).toBeInTheDocument();
    expect(screen.queryByText(/^Fetched/)).not.toBeInTheDocument();
    const usage = await openTab("Usage");
    expect(usage.queryByRole("grid", { name: "Fetch attempts" })).not.toBeInTheDocument();
    expect(usage.getByRole("grid", { name: "Usage" })).toBeInTheDocument();
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

  it("lists a validation problem's field errors and marks the inputs they name", async () => {
    stubScrape({
      "POST /v1/scrape": () =>
        problem(422, {
          type: "validation",
          title: "Invalid request",
          errors: [
            { field: "url", reason: "not a public address" },
            { field: "schema.inline.fields", reason: "unknown type" },
          ],
        }),
    });
    await openScrape();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");

    await submit();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("url: not a public address");
    expect(alert).toHaveTextContent("schema.inline.fields: unknown type");
    expect(screen.getByRole("textbox", { name: "URL" })).toHaveAttribute("aria-invalid", "true");
  });

  it("says so when the API answers without a problem body", async () => {
    stubScrape({ "POST /v1/scrape": () => new Response("upstream down", { status: 502 }) });
    await openScrape();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");

    await submit();

    expect(await screen.findByRole("alert")).toHaveTextContent("The scrape failed (HTTP 502).");
  });
});

describe("scrape playground: the output area", () => {
  it("keeps one output box from the first run on, through pending, failed and done", async () => {
    const replies: ((response: Response) => void)[] = [];
    stubScrape({
      "POST /v1/scrape": () =>
        new Promise<Response>((resolve) => {
          replies.push(resolve);
        }),
    });
    await openScrape();
    expect(screen.queryByRole("region", { name: "Output" })).not.toBeInTheDocument();
    await typeUrl();

    await submit();
    const output = screen.getByRole("region", { name: "Output" });
    expect(within(output).getByLabelText("Scraping")).toBeInTheDocument();
    replies[0]?.(problem(404, { type: "not_found", title: "Not found" }));
    expect(await within(output).findByRole("alert")).toHaveTextContent("Not found");
    await submit();
    replies[1]?.(Response.json(scrapeResponse()));

    expect(await within(output).findByText("extracted")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Output" })).toBe(output);
    expect(output).toHaveClass("min-h-playground-output");
  });
});
