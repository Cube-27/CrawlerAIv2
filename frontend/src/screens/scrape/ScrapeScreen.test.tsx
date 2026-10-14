import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vite-plus/test";
import { routes } from "../../app/router";
import type { RecordField, ScrapeResponse } from "../../api/scrape";
import { problem, stubApi } from "../../test/api";

// The form types into several fields with user-event, which is slow in jsdom.
vi.setConfig({ testTimeout: 20_000 });

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
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: ["/scrape"] })} />);
  await userEvent.type(screen.getByLabelText(/API key/), "ck_first");
  await userEvent.click(screen.getByRole("button", { name: "Connect" }));
  await screen.findByRole("heading", { level: 1, name: "Scrape" });
}

async function choose(groupName: string, option: string) {
  await userEvent.click(
    within(screen.getByRole("radiogroup", { name: groupName })).getByLabelText(option),
  );
}

async function fillRecordsByIdForm() {
  await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/items/1");
  await userEvent.click(screen.getByRole("checkbox", { name: "Records" }));
  await choose("Schema", "Stored schema");
  await userEvent.click(screen.getByRole("button", { name: /Stored schema/ }));
  await userEvent.click(await screen.findByRole("option", { name: "item_detail version 2" }));
  await choose("Page kind", "Detail");
}

async function submit() {
  await userEvent.click(screen.getByRole("button", { name: "Scrape" }));
}

async function openTab(name: string) {
  await userEvent.click(await screen.findByRole("tab", { name }));
  return within(screen.getByRole("tabpanel", { name }));
}

describe("scrape screen: the request", () => {
  it("is in the main navigation", async () => {
    await openScrape();

    expect(
      within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", {
        name: "Scrape",
      }),
    ).toHaveAttribute("href", "/scrape");
  });

  it("posts the request SPEC-07 defines, with the key, and leaves empty limits to the server", async () => {
    const calls = stubApi({
      "POST /v1/scrape": () => Response.json(withRecords),
      "GET /v1/schemas": schemaList,
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
      authorization: "Bearer ck_first",
      body: {
        url: "https://store.test/items/1",
        formats: ["markdown", "records"],
        schema: { id: SCHEMA_ID },
        page_kind: "detail",
        fetch: { method_hint: "auto" },
      },
    });
  });

  it("sends the limits and fetch hint that were entered", async () => {
    const calls = stubApi({ "POST /v1/scrape": () => Response.json(scrapeResponse()) });
    await openScrape();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");
    await userEvent.click(screen.getByRole("checkbox", { name: "Markdown" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Links" }));
    await choose("Fetch method", "Browser");
    await userEvent.type(screen.getByRole("textbox", { name: "Max age (seconds)" }), "3600");
    await userEvent.type(screen.getByRole("textbox", { name: "Timeout (seconds)" }), "90");
    await userEvent.type(screen.getByRole("textbox", { name: "LLM call budget" }), "0");

    await submit();

    await screen.findByText("extracted");
    expect(calls[0]?.body).toEqual({
      url: "https://store.test/a",
      formats: ["links"],
      schema: null,
      page_kind: null,
      fetch: { method_hint: "browser" },
      max_age: 3600,
      timeout_s: 90,
      budget: { llm_calls: 0 },
    });
  });
});

describe("scrape screen: records and schemas", () => {
  it("shows each record field with its value, status, confidence, evidence, source and locator", async () => {
    stubApi({
      "POST /v1/scrape": () => Response.json(withRecords),
      "GET /v1/schemas": schemaList,
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
    stubApi({
      "POST /v1/scrape": () => Response.json(withRecords),
      "GET /v1/schemas": schemaList,
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
    stubApi({
      "POST /v1/scrape": () => Response.json(withRecords),
      "GET /v1/schemas": schemaList,
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
    stubApi({
      "POST /v1/scrape": () => Response.json(withRecords),
      "GET /v1/schemas": schemaList,
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

  it("types an inline schema's records by the schema sent, without reading a stored one", async () => {
    const calls = stubApi({ "POST /v1/scrape": () => Response.json(withRecords) });
    await openScrape();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");
    await userEvent.click(screen.getByRole("checkbox", { name: "Records" }));
    await choose("Schema", "Inline JSON");
    // user-event reads `{` and `[` as key descriptors; doubled, they type the character.
    await userEvent.type(
      screen.getByRole("textbox", { name: "Schema JSON" }),
      '{{"name":"item","fields":{{"price":{{"type":"money"}}}',
    );
    await choose("Page kind", "Detail");

    await submit();

    const records = await openTab("Records");
    expect(
      within(records.getByRole("row", { name: /price/ })).getByText("19.90 EUR"),
    ).toBeVisible();
    expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual(["POST /v1/scrape"]);
    expect(calls[0]?.body).toMatchObject({
      schema: { inline: { name: "item", fields: { price: { type: "money" } } } },
    });
  });

  it("refuses inline schema text that is not a JSON object", async () => {
    const calls = stubApi({});
    await openScrape();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");
    await choose("Schema", "Inline JSON");
    await userEvent.type(screen.getByRole("textbox", { name: "Schema JSON" }), "[[1]");

    await submit();

    expect(screen.getByRole("textbox", { name: "Schema JSON" })).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(calls).toEqual([]);
  });

  it("offers detail pages only for records, which the server refuses for listing pages", async () => {
    const calls = stubApi({});
    await openScrape();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");
    await choose("Page kind", "Listing");

    await userEvent.click(screen.getByRole("checkbox", { name: "Records" }));

    const kinds = within(screen.getByRole("radiogroup", { name: "Page kind" }));
    expect(kinds.getByLabelText("Listing")).toBeDisabled();
    expect(kinds.getByLabelText("Listing")).not.toBeChecked();
    expect(screen.getByText("Records of listing pages are not available yet.")).toBeInTheDocument();
    await submit();
    expect(calls).toEqual([]);
  });

  it("requires a page kind when records are asked for", async () => {
    const calls = stubApi({});
    await openScrape();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");
    await userEvent.click(screen.getByRole("checkbox", { name: "Records" }));

    await submit();

    expect(calls).toEqual([]);
  });

  it("shows a prompt's draft schema and types the records by it", async () => {
    const draft = { ...itemSchema, name: "drafted", origin: "prompt_draft" };
    const calls = stubApi({
      "POST /v1/scrape": () => Response.json({ ...withRecords, schema: draft }),
    });
    await openScrape();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");
    await userEvent.click(screen.getByRole("checkbox", { name: "Records" }));
    await choose("Schema", "From a prompt");
    await userEvent.type(screen.getByRole("textbox", { name: "Prompt" }), "the item's price");
    await choose("Page kind", "Detail");

    await submit();

    const schemaTab = await openTab("Draft schema");
    expect(schemaTab.getByText("drafted")).toBeInTheDocument();
    expect(schemaTab.getByText("prompt_draft")).toBeInTheDocument();
    expect(schemaTab.getByRole("link", { name: "Edit as schema" })).toHaveAttribute(
      "href",
      `/schemas/new?from=${SCHEMA_ID}`,
    );
    const records = await openTab("Records");
    expect(
      within(records.getByRole("row", { name: /price/ })).getByText("19.90 EUR"),
    ).toBeVisible();
    expect(calls).toHaveLength(1);
    expect(calls[0]?.body).toMatchObject({ schema: { prompt: "the item's price" } });
  });
});

describe("scrape screen: formats and problems", () => {
  it("shows each returned format in its own tab", async () => {
    stubApi({
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
    stubApi({
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
    stubApi({
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
    stubApi({
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
    stubApi({
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
    stubApi({ "POST /v1/scrape": () => new Response("upstream down", { status: 502 }) });
    await openScrape();
    await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");

    await submit();

    expect(await screen.findByRole("alert")).toHaveTextContent("The scrape failed (HTTP 502).");
  });
});
