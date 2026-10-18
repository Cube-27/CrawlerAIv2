import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { JsonValuesItem } from "../../../api/jobs";
import { stubApi, type Call } from "../../../test/api";
import { runApi } from "../../../test/runs";
import {
  closeOptions,
  openOptions,
  fill,
  openPlayground,
  pick,
  posted,
  toggleFormats,
} from "../../../test/playground";

// `fetch` answers the crawl, job, results and events endpoints with the shapes jobs spec and frontend spec
// define.

const JOB_ID = "0192a000-0000-7000-8000-0000000000c1";

const ITEM: JsonValuesItem = {
  url: "https://shop.test/items/1",
  outcome: "extracted",
  records: [{ title: "Blue mug" }],
};

function crawlApi(replies: Parameters<typeof stubApi>[0] = {}): Call[] {
  return runApi(
    {
      submit: "POST /v1/crawl",
      jobId: JOB_ID,
      kind: "crawl",
      request: { url: "https://shop.test/", formats: ["markdown"] },
      items: [ITEM],
    },
    replies,
  );
}

async function typeUrl(text: string) {
  await fill(screen.getByRole("textbox", { name: "URL" }), text);
}

async function start() {
  await userEvent.click(screen.getByRole("button", { name: "Start crawl" }));
}

describe("crawl playground", () => {
  it("posts the crawl request jobs spec defines from the bar, toolbar and options, and runs it on the page", async () => {
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
    await fill(options.getByRole("textbox", { name: "Max rows" }), "30");
    await closeOptions();

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
      fetch: { method_hint: "auto", max_rows: 30 },
    });
  });
});
