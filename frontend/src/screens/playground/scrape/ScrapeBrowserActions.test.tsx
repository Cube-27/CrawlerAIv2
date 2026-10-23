import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { ScrapeResponse } from "../../../api/scrape";
import { stubApi } from "../../../test/api";
import { closeOptions, openOptions, openPlayground, pick, posted } from "../../../test/playground";

// Scrape's browser actions options: a listing's only, mapped to `browser_actions`.

const response: ScrapeResponse = {
  job_id: "0192a000-0000-7000-8000-0000000000j1",
  capture_id: "0192a000-0000-7000-8000-0000000000c1",
  url: "https://store.test/a",
  final_url: "https://store.test/a",
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
    llm_calls: 0,
    llm_tokens_in: 0,
    llm_tokens_out: 0,
    browser_seconds: 3,
    http_requests: 0,
  },
};

function stubScrape() {
  return stubApi({
    "GET /v1/schemas": () => Response.json({ items: [] }),
    "POST /v1/scrape": () => Response.json(response),
  });
}

async function openScrape() {
  await openPlayground("/");
  await userEvent.type(screen.getByRole("textbox", { name: "URL" }), "https://store.test/a");
}

async function submit() {
  await userEvent.click(screen.getByRole("button", { name: "Scrape" }));
}

describe("scrape playground: browser actions", () => {
  it("sends a listing's browser actions with the records and paging hint that were set", async () => {
    const calls = stubScrape();
    await openScrape();
    const options = await openOptions();
    await pick(/Page kind/, "Listing");
    await userEvent.click(options.getByRole("switch", { name: "Browser actions" }));
    await userEvent.type(options.getByRole("textbox", { name: "Records" }), "30");
    await pick(/Paging hint/, "Scroll");
    await closeOptions();

    await submit();

    await screen.findByText("extracted");
    expect(posted(calls)).toMatchObject({
      page_kind: "listing",
      browser_actions: { records: 30, hint: "scroll" },
    });
  });
});
