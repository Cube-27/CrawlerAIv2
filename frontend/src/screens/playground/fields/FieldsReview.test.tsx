import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { SchemaDef } from "../../../api/schemas";
import { problem, stubApi, type Call } from "../../../test/api";
import {
  fill,
  openOptions,
  openPlayground,
  pick,
  posted,
  toggleFormats,
} from "../../../test/playground";
import { runApi, schemaList } from "../../../test/runs";
import { curlBody } from "../../../test/shell";

// Additional fields (SPEC-14 §4.10): names typed as chips become `schema.fields`; the run first shows the schema
// `POST /v1/schemas/draft` drafts from them, for review. `fetch` answers with the shapes SPEC-07 and SPEC-10 define.

const JOB_ID = "0192a000-0000-7000-8000-0000000000f1";

const DRAFT: SchemaDef = {
  id: "0192a000-0000-7000-8000-0000000000d1",
  name: "draft_0a1b2c3d4e5f",
  origin: "prompt_draft",
  status: "active",
  page_kind: "detail",
  required_groups: [],
  fields: {
    colour: { type: "text", required: false, scope: "row" },
    price: { type: "money", required: true, scope: "row" },
  },
};

function draftReply(): Response {
  return Response.json(DRAFT);
}

function stubScrape(draft: (call: Call) => Response = draftReply): Call[] {
  return stubApi({
    "GET /v1/schemas": schemaList,
    "POST /v1/schemas/draft": draft,
    // Only the body matters here.
    "POST /v1/scrape": () => problem(503, { title: "Busy" }),
  });
}

/** Opens Scrape with a URL, the detail page kind and the field chips `names`; returns the options panel. */
async function scrapeWithFields(...names: string[]) {
  await openPlayground("/");
  await fill(screen.getByRole("textbox", { name: "URL" }), "https://shop.test/items/1");
  const options = await openOptions();
  await pick(/Page kind/, "Detail");
  for (const name of names)
    await fill(options.getByRole("textbox", { name: "Fields" }), name, true);
  return options;
}

async function review() {
  return within(await screen.findByRole("dialog", { name: "Review the drafted schema" }));
}

function posts(calls: readonly Call[], path: string): Call[] {
  return calls.filter((call) => call.method === "POST" && call.path === path);
}

describe("additional fields: chips", () => {
  it("adds each name as a chip and keeps a name that is not a schema field name in the field, with why", async () => {
    stubScrape();
    const options = await scrapeWithFields("price", "colour");

    await fill(options.getByRole("textbox", { name: "Fields" }), "Unit price", true);

    const chips = within(options.getByRole("grid", { name: "Fields" }));
    expect(chips.getAllByRole("row").map((row) => row.textContent)).toEqual(["price", "colour"]);
    expect(options.getByRole("textbox", { name: "Fields" })).toHaveValue("Unit price");
    expect(
      options.getByText("Use lowercase letters, digits and _, starting with a letter."),
    ).toBeInTheDocument();
  });
});

describe("additional fields: the draft review", () => {
  it("shows the draft before the run, and Run as drafted posts the names, the body Get code shows", async () => {
    const calls = stubScrape();
    await scrapeWithFields("price", "colour");
    await userEvent.click(screen.getByRole("button", { name: "Get code" }));
    const getCode = within(await screen.findByRole("dialog"));
    const curl = curlBody(getCode.getByRole("region", { name: "cURL code" }).textContent);
    await userEvent.keyboard("{Escape}");

    await userEvent.click(screen.getByRole("button", { name: "Scrape" }));
    const drawer = await review();
    expect(await drawer.findByRole("textbox", { name: "Name" })).toHaveValue(DRAFT.name);
    expect(posts(calls, "/v1/scrape")).toEqual([]);
    await userEvent.click(drawer.getByRole("button", { name: "Run" }));

    expect(posts(calls, "/v1/schemas/draft").map(({ body }) => body)).toEqual([
      { fields: ["price", "colour"], page_kind: "detail" },
    ]);
    const body = posts(calls, "/v1/scrape")[0]?.body;
    expect(body).toEqual({
      url: "https://shop.test/items/1",
      formats: ["markdown", "records"],
      schema: { fields: ["price", "colour"] },
      page_kind: "detail",
      fetch: { method_hint: "auto" },
    });
    expect(curl).toEqual(body);
  });

  it("posts an edited draft inline, under the name it was given", async () => {
    const calls = stubScrape();
    await scrapeWithFields("price", "colour");
    await userEvent.click(screen.getByRole("button", { name: "Scrape" }));
    const drawer = await review();
    const name = await drawer.findByRole("textbox", { name: "Name" });

    await userEvent.clear(name);
    await userEvent.type(name, "my_items");
    await userEvent.click(drawer.getByRole("button", { name: "Run" }));

    expect(posts(calls, "/v1/scrape")[0]?.body).toMatchObject({
      schema: {
        inline: {
          name: "my_items",
          page_kind: "detail",
          required_groups: [],
          fields: DRAFT.fields,
        },
      },
    });
  });

  it("shows a draft the server could not give as its problem, and closing the drawer sends nothing", async () => {
    const calls = stubScrape(() => problem(503, { title: "No LLM provider is configured" }));
    await scrapeWithFields("price");
    await userEvent.click(screen.getByRole("button", { name: "Scrape" }));
    const drawer = await review();

    expect(await drawer.findByText("No LLM provider is configured")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/v1/scrape")).toEqual([]);
  });

  it("batch: posts records with the reviewed names as schema.fields", async () => {
    const calls = runApi(
      { submit: "POST /v1/batch/scrape", jobId: JOB_ID, kind: "batch_scrape" },
      { "POST /v1/schemas/draft": draftReply },
    );
    await openPlayground("/batch");
    await fill(screen.getByRole("textbox", { name: "URLs" }), "https://shop.test/a");
    // A batch asks for records alone (SPEC-10 §4.3).
    await toggleFormats("Markdown");
    const options = await openOptions();
    await pick(/Page kind/, "Detail");
    await fill(options.getByRole("textbox", { name: "Fields" }), "price", true);

    await userEvent.click(screen.getByRole("button", { name: "Start batch" }));
    await userEvent.click((await review()).getByRole("button", { name: "Run" }));

    expect(posted(calls.filter(({ path }) => path !== "/v1/schemas/draft"))).toEqual({
      urls: ["https://shop.test/a"],
      formats: ["records"],
      schema: { fields: ["price"] },
      page_kind: "detail",
      fetch: { method_hint: "auto" },
    });
  });

  it("crawl: drafts the names for its rules' page kind and posts them as schema.fields", async () => {
    const calls = runApi(
      { submit: "POST /v1/crawl", jobId: JOB_ID, kind: "crawl" },
      { "POST /v1/schemas/draft": draftReply },
    );
    await openPlayground("/crawl");
    await fill(screen.getByRole("textbox", { name: "URL" }), "https://shop.test/");
    const options = await openOptions();
    await fill(options.getByRole("textbox", { name: "Fields" }), "price", true);
    await userEvent.click(options.getByRole("button", { name: "Add rule" }));
    await fill(options.getByRole("textbox", { name: "Pattern 1" }), "https://shop.test/items/*");
    await pick(/Page kind 1/, "Detail");

    await userEvent.click(screen.getByRole("button", { name: "Start crawl" }));
    await userEvent.click((await review()).getByRole("button", { name: "Run" }));

    expect(posts(calls, "/v1/schemas/draft").map(({ body }) => body)).toEqual([
      { fields: ["price"], page_kind: "detail" },
    ]);
    expect(posts(calls, "/v1/crawl")[0]?.body).toMatchObject({
      formats: ["records"],
      schema: { fields: ["price"] },
      page_kind_rules: [{ pattern: "https://shop.test/items/*", page_kind: "detail" }],
    });
  });
});
