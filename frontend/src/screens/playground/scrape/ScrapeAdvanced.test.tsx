import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { ScrapeResponse } from "../../../api/scrape";
import { stubApi } from "../../../test/api";
import { closeOptions, openOptions, openPlayground, pick, posted } from "../../../test/playground";

// Scrape's Advanced options (D-1430, D-1436): the request context, cache and page actions, sent as `fetch` members.

const response: ScrapeResponse = {
  job_id: "0192a000-0000-7000-8000-0000000000j1",
  capture_id: "0192a000-0000-7000-8000-0000000000c1",
  url: "https://store.test/a",
  final_url: "https://store.test/a",
  fetched_at: "2026-10-13T10:00:00Z",
  outcome: "extracted",
  fetch: { method: "browser", status_code: 200, block_class: "ok", adapter: null, attempts: [] },
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
  await screen.findByText("extracted");
}

describe("scrape playground: advanced options", () => {
  it("sends a click step written in the actions editor", async () => {
    const calls = stubScrape();
    await openScrape();
    const options = await openOptions();
    await userEvent.click(options.getByRole("button", { name: "Add step" }));
    await userEvent.type(options.getByRole("textbox", { name: "Step 1 CSS selector" }), ".more");
    await closeOptions();

    await submit();

    expect(posted(calls)).toMatchObject({
      fetch: { method_hint: "auto", actions: [{ type: "click", selector: ".more" }] },
    });
  });

  it("sends steps in the order they were moved to", async () => {
    const calls = stubScrape();
    await openScrape();
    const options = await openOptions();
    await userEvent.click(options.getByRole("button", { name: "Add step" }));
    await userEvent.type(options.getByRole("textbox", { name: "Step 1 CSS selector" }), "#q");
    await userEvent.click(options.getByRole("button", { name: "Add step" }));
    await pick(/Step 2 kind/, "Scroll");
    await userEvent.click(options.getByRole("button", { name: "Move step 2 up" }));
    // The moved row's button is now disabled (the row is first), and a disabled control keeps no focus to Escape from.
    await userEvent.click(options.getByRole("textbox", { name: "Wait for" }));
    await closeOptions();

    await submit();

    expect(posted(calls)).toMatchObject({
      fetch: {
        actions: [
          { type: "scroll", to: "bottom" },
          { type: "click", selector: "#q" },
        ],
      },
    });
  });

  it("sends no Advanced member for an untouched section", async () => {
    const calls = stubScrape();
    await openScrape();

    await submit();

    expect((posted(calls) as { fetch: object }).fetch).toEqual({ method_hint: "auto" });
  });

  it("sends the cookies, wait for and cache that were set", async () => {
    const calls = stubScrape();
    await openScrape();
    const options = await openOptions();
    await userEvent.type(options.getByRole("textbox", { name: "Cookies" }), "sid=abc; theme=dark");
    await userEvent.type(options.getByRole("textbox", { name: "Wait for" }), "1500");
    await pick(/Cache/, "Always fetch");
    await closeOptions();

    await submit();

    expect(posted(calls)).toMatchObject({
      fetch: { cookies: { sid: "abc", theme: "dark" }, wait_for: 1500, cache: "bypass" },
    });
  });
});
