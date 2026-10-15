import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vite-plus/test";
import { routes } from "../../../app/router";
import type { RecordField, ScrapeResponse } from "../../../api/scrape";
import { problem, stubApi, type Call } from "../../../test/api";

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
  version: 2,
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
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: ["/"] })} />);
  await screen.findByRole("heading", { level: 1, name: "Playground" });
}

async function typeUrl(url = "https://store.test/a") {
  await userEvent.type(screen.getByRole("textbox", { name: "URL" }), url);
}

/** The trigger of the Select named by `name`; its help icon has the name too. */
function selectTrigger(name: RegExp): HTMLElement {
  const trigger = screen
    .getAllByRole("button", { name })
    .find((button) => button.getAttribute("aria-haspopup") === "listbox");
  if (trigger === undefined) throw new Error(`no select named ${String(name)}`);
  return trigger;
}

/** Picks `option` in the Select named by `name`. */
async function pick(name: RegExp, option: string) {
  await userEvent.click(selectTrigger(name));
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

/** Stubs the API with `replies`; the toolbar's schema list is always read. */
function stubScrape(replies: Parameters<typeof stubApi>[0]) {
  return stubApi({ "GET /v1/schemas": schemaList, ...replies });
}

/** The body of the one scrape that was posted. */
function posted(calls: readonly Call[]): unknown {
  const posts = calls.filter(({ method }) => method === "POST");
  expect(posts).toHaveLength(1);
  return posts[0]?.body;
}

/** Toggles each of `formats` in the toolbar's Format select, then closes it. */
async function toggleFormats(...formats: string[]) {
  await userEvent.click(selectTrigger(/Format/));
  for (const format of formats) {
    await userEvent.click(await screen.findByRole("option", { name: format }));
  }
  await userEvent.keyboard("{Escape}");
}

function optionsButton(): HTMLElement {
  return screen.getByRole("button", { name: "Options" });
}

async function openOptions() {
  await userEvent.click(optionsButton());
  return within(screen.getByRole("region", { name: "Options" }));
}

async function fillRecordsByIdForm() {
  await typeUrl("https://store.test/items/1");
  await pick(/Schema/, "item_detail version 2");
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

  it("opens the options inline under the command bar, with Advanced collapsed, and no dialog", async () => {
    await openScrape();
    expect(screen.queryByRole("region", { name: "Options" })).not.toBeInTheDocument();

    const options = await openOptions();

    expect(screen.getByRole("button", { name: "Options" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(options.getByRole("switch", { name: "Metadata in JSON" })).toBeVisible();
    expect(options.getByRole("button", { name: "Advanced" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(options.queryByRole("textbox", { name: "Max age (seconds)" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("marks Options exactly when a setting differs from its default, until Reset settings", async () => {
    await openScrape();
    const options = await openOptions();
    expect(optionsButton()).not.toHaveAccessibleDescription();

    await userEvent.click(options.getByRole("switch", { name: "Metadata in JSON" }));
    expect(optionsButton()).toHaveAccessibleDescription("Settings changed");

    await userEvent.click(options.getByRole("switch", { name: "Metadata in JSON" }));
    expect(optionsButton()).not.toHaveAccessibleDescription();

    await userEvent.click(options.getByRole("button", { name: "Advanced" }));
    await userEvent.type(options.getByRole("textbox", { name: "Timeout (seconds)" }), "90");
    await userEvent.tab();
    expect(optionsButton()).toHaveAccessibleDescription("Settings changed");

    await userEvent.click(options.getByRole("button", { name: "Reset settings" }));
    expect(optionsButton()).not.toHaveAccessibleDescription();
    expect(options.getByRole("textbox", { name: "Timeout (seconds)" })).toHaveValue("");
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

    await screen.findByRole("tab", { name: "Records" });
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

  it("sends the formats, limits and fetch method that were set, and leaves empty limits to the server", async () => {
    const calls = stubScrape({ "POST /v1/scrape": () => Response.json(scrapeResponse()) });
    await openScrape();
    await typeUrl();
    await toggleFormats("Markdown", "Links");
    const options = await openOptions();
    await userEvent.click(options.getByRole("button", { name: "Advanced" }));
    await pick(/Fetch method/, "Browser");
    await userEvent.type(options.getByRole("textbox", { name: "Max age (seconds)" }), "3600");
    await userEvent.type(options.getByRole("textbox", { name: "LLM call budget" }), "0");

    await submit();

    await screen.findByText("extracted");
    expect(posted(calls)).toEqual({
      url: "https://store.test/a",
      formats: ["links"],
      schema: null,
      page_kind: null,
      fetch: { method_hint: "browser" },
      max_age: 3600,
      budget: { llm_calls: 0 },
    });
  });

  it("asks for the metadata format with Metadata in JSON", async () => {
    const calls = stubScrape({ "POST /v1/scrape": () => Response.json(scrapeResponse()) });
    await openScrape();
    await typeUrl();
    const options = await openOptions();
    await userEvent.click(options.getByRole("switch", { name: "Metadata in JSON" }));

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
    expect(screen.getByText("Choose a format, Metadata in JSON or a schema.")).toBeInTheDocument();
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
    expect(screen.getByRole("region", { name: "Options" })).toBeInTheDocument();
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
      version: 1,
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
    await pick(/Schema/, "item_listing version 1");

    await submit();

    expect(calls.filter(({ method }) => method === "POST")).toEqual([]);
    expect(screen.getByRole("region", { name: "Options" })).toBeInTheDocument();
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

    const records = await openTab("Records");
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

    const records = await openTab("Records");
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

    const records = await openTab("Records");
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

    const records = await openTab("Records");
    expect(within(records.getByRole("row", { name: /title/ })).getByText("Blue mug")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
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
    expect(screen.queryByRole("tab", { name: "Records" })).not.toBeInTheDocument();
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
    const fetchTab = await openTab("Fetch");
    const httpAttempt = within(fetchTab.getByRole("row", { name: "http" }));
    expect(httpAttempt.getByText("shell")).toBeInTheDocument();
    expect(httpAttempt.getByText("120")).toBeInTheDocument();
    const usage = await openTab("Usage");
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
    expect(screen.queryByRole("tab", { name: "Fetch" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Usage" })).toBeInTheDocument();
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
