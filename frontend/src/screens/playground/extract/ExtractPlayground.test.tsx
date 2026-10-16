import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { Call } from "../../../test/api";
import { runApi, SCHEMA_ID } from "../../../test/runs";
import {
  closeOptions,
  fill,
  openOptions,
  openPlayground,
  pick,
  posted,
} from "../../../test/playground";

// `fetch` answers the extract, job, results and events endpoints with the shapes SPEC-10 §4.2, §4.6 and SPEC-14 §4.4
// define.

const JOB_ID = "0192a000-0000-7000-8000-0000000000e1";

function extractApi(request: Record<string, unknown> = {}): Call[] {
  return runApi({ submit: "POST /v1/extract", jobId: JOB_ID, kind: "extract", request });
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
    await pick(/Schema$/, "item_detail");
    const options = await openOptions();
    await fill(
      options.getByRole("textbox", { name: "More URLs" }),
      "https://shop.test/items/*",
      true,
    );
    await closeOptions();

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
    await fill(options.getByRole("textbox", { name: "LLM call limit" }), "3");
    await closeOptions();

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

    const options = within(await screen.findByRole("dialog", { name: "Options" }));
    expect(
      options.getByText("Choose a stored schema in the toolbar, or another source."),
    ).toBeInTheDocument();
    await pick(/Schema source/, "Inline JSON");
    await fill(options.getByRole("textbox", { name: "Schema JSON" }), '{"name": "x"}');
    await closeOptions();
    await extract();
    const reopened = within(await screen.findByRole("dialog", { name: "Options" }));
    expect(await reopened.findByText("Choose the page kind of the records.")).toBeInTheDocument();
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
    expect(options.getByRole("grid", { name: "More URLs" })).toHaveTextContent(
      "https://shop.test/items/*",
    );
  });
});
