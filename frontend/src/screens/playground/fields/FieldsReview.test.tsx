import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { SchemaDef } from "../../../api/schemas";
import { problem, stubApi, type Call } from "../../../test/api";
import { closeOptions, fill, openOptions, openPlayground, pick } from "../../../test/playground";
import { schemaList } from "../../../test/runs";
import { curlBody } from "../../../test/shell";

// Additional fields (frontend spec): names typed as chips become `schema.fields`; the run first shows the schema
// `POST /v1/schemas/draft` drafts from them, for review. `fetch` answers with the shapes rest-api spec and jobs spec define.

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

describe("additional fields: the draft review", () => {
  it("shows the draft before the run, and Run as drafted posts the names, the body Get code shows", async () => {
    const calls = stubScrape();
    await scrapeWithFields("price", "colour");
    await closeOptions();
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
    await closeOptions();
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
});
