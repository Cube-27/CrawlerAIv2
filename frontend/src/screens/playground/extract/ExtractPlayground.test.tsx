import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { JsonValuesPage } from "../../../api/jobs";
import { stubApi, type Call } from "../../../test/api";
import { jobSummary } from "../../../test/jobs";
import { fill, openOptions, openPlayground, pick, posted } from "../../../test/playground";

// `fetch` answers the extract, job, results and events endpoints with the shapes SPEC-10 §4.2, §4.6 and SPEC-14 §4.4
// define.

const JOB_ID = "0192a000-0000-7000-8000-0000000000e1";
const JOB = `/v1/jobs/${JOB_ID}`;
const SCHEMA_ID = "0192a000-0000-7000-8000-0000000000s1";

const QUIET = () =>
  new Response(new ReadableStream(), { headers: { "content-type": "text/event-stream" } });

function extractApi(request: Record<string, unknown> = {}): Call[] {
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
    "POST /v1/extract": () => Response.json({ job_id: JOB_ID }, { status: 202 }),
    [`GET ${JOB}`]: () => Response.json(jobSummary({ id: JOB_ID, kind: "extract", request })),
    [`GET ${JOB}/events`]: QUIET,
    [`GET ${JOB}/results`]: () =>
      Response.json({
        format: "json_values",
        items: [],
        next_cursor: null,
      } satisfies JsonValuesPage),
  });
}

async function extract() {
  await userEvent.click(screen.getByRole("button", { name: "Extract" }));
}

describe("extract playground", () => {
  it("is a mode tab under Pages at /extract", async () => {
    extractApi();
    await openPlayground("/extract");

    const pages = screen.getByRole("tablist", { name: "Pages" });
    expect(within(pages).getByRole("tab", { name: "Extract" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("posts the URL, more URLs and globs, and a stored schema of its own page kind", async () => {
    const calls = extractApi();
    await openPlayground("/extract");
    await fill(screen.getByRole("textbox", { name: "URL" }), "shop.test/items/1");
    await pick(/Schema$/, "item_detail version 2");
    const options = await openOptions();
    await fill(
      options.getByRole("textbox", { name: "More URLs or globs" }),
      "https://shop.test/items/*",
      true,
    );

    await extract();

    await screen.findByRole("grid", { name: "Pages" });
    expect(posted(calls)).toEqual({
      urls: ["https://shop.test/items/1", "https://shop.test/items/*"],
      schema: { id: SCHEMA_ID },
      page_kind: "detail",
      fetch: { method_hint: "auto" },
    });
  });

  it("drafts the schema from a prompt, for the page kind chosen", async () => {
    const calls = extractApi();
    await openPlayground("/extract");
    await fill(screen.getByRole("textbox", { name: "URL" }), "https://shop.test/items/1");
    const options = await openOptions();
    await pick(/Schema source/, "From a prompt");
    await fill(options.getByRole("textbox", { name: "Prompt" }), "title and price");
    await pick(/Page kind/, "Detail");
    await userEvent.click(options.getByRole("button", { name: "Advanced" }));
    await fill(options.getByRole("textbox", { name: "LLM call budget" }), "3");

    await extract();

    await screen.findByRole("grid", { name: "Pages" });
    expect(posted(calls)).toEqual({
      urls: ["https://shop.test/items/1"],
      schema: { prompt: "title and price" },
      page_kind: "detail",
      fetch: { method_hint: "auto" },
      budget: { llm_calls: 3 },
    });
  });

  it("says what a request without a schema or page kind lacks, and sends nothing", async () => {
    const calls = extractApi();
    await openPlayground("/extract");
    await fill(screen.getByRole("textbox", { name: "URL" }), "https://shop.test/items/1");

    await extract();

    const options = within(await screen.findByRole("region", { name: "Options" }));
    expect(
      options.getByText("Choose a stored schema in the toolbar, or another source."),
    ).toBeInTheDocument();
    await pick(/Schema source/, "Inline JSON");
    await fill(options.getByRole("textbox", { name: "Schema JSON" }), '{"name": "x"}');
    await extract();
    expect(await options.findByText("Choose the page kind of the records.")).toBeInTheDocument();
    expect(calls.filter(({ method }) => method === "POST")).toEqual([]);
  });

  it("shows an extract job's request read-only, its inline schema as JSON", async () => {
    extractApi({
      urls: ["https://shop.test/items/1", "https://shop.test/items/*"],
      schema: { inline: { name: "item", page_kind: "detail" } },
      page_kind: "detail",
      limit: 100,
      fetch: { method_hint: "http" },
    });
    await openPlayground(`/extract?job=${JOB_ID}`);

    const url = screen.getByRole("textbox", { name: "URL" });
    await waitFor(() => {
      expect(url).toHaveValue("https://shop.test/items/1");
    });
    expect(url).toBeDisabled();
    const options = await openOptions();
    expect(options.getByRole("textbox", { name: "Schema JSON" })).toHaveValue(
      JSON.stringify({ name: "item", page_kind: "detail" }, null, 2),
    );
    expect(options.getByRole("grid", { name: "More URLs or globs" })).toHaveTextContent(
      "https://shop.test/items/*",
    );
  });
});
