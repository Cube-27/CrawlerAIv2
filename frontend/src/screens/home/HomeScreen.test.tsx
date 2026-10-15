import { render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vite-plus/test";
import { routes } from "../../app/router";
import type { JobPage, JobSummary } from "../../api/jobs";
import type { SchemaDef } from "../../api/schemas";
import type { CostReport } from "../../api/usage";
import { problem, stubApi } from "../../test/api";

const JOB_ID = "0192a000-0000-7000-8000-000000000901";

const JOB: JobSummary = {
  id: JOB_ID,
  kind: "crawl",
  status: "running",
  counts: { queued: 1, claimed: 0, done: 2, failed: 0, cancelled: 0 },
  outcomes: {
    extracted: 2,
    partial: 0,
    unchanged: 0,
    links_only: 0,
    blocked: 0,
    shell: 0,
    not_found: 0,
    no_match: 0,
    failed: 0,
  },
  usage: { pages_fetched: 2 },
  llm_cost_usd: null,
  created_at: "2026-10-14T09:00:00Z",
  started_at: "2026-10-14T09:00:01Z",
  finished_at: null,
  engine_version: "0.0.0",
  webhook_url: null,
  cancel_requested: false,
};

function schema(name: string, version: number): SchemaDef {
  return {
    id: `0192a000-0000-7000-8000-00000000010${String(version)}`,
    name,
    version,
    origin: "user",
    status: "active",
    page_kind: "detail",
    required_groups: [["title"]],
    fields: { title: { type: "text", required: true, scope: "row" } },
  };
}

const COSTS: CostReport = {
  start: "2026-09-15",
  end: "2026-10-14",
  currency: "USD",
  total: { calls: 12, estimated_usd: 0.4321, tokens_in: 1000, tokens_out: 100, unpriced_tokens: 0 },
  breakdown: [],
  days: [],
  top_jobs: [],
};

function jobsReply(): Response {
  const page: JobPage = { items: [JOB], next_cursor: null };
  return Response.json(page);
}

function renderOverview() {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: ["/"] })} />);
}

describe("overview", () => {
  it("shows the quick actions, the headline numbers and the recent jobs", async () => {
    const calls = stubApi({
      "GET /v1/jobs": jobsReply,
      "GET /v1/schemas": () =>
        Response.json({ items: [schema("item_detail", 1), schema("item_detail", 2)] }),
      "GET /v1/usage/llm": () => Response.json(COSTS),
    });
    renderOverview();

    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
    expect(screen.getByRole("link", { name: /Scrape a page/ })).toHaveAttribute("href", "/scrape");
    expect(screen.getByRole("link", { name: /Define a schema/ })).toHaveAttribute(
      "href",
      "/schemas/new",
    );
    expect(await screen.findByText("$0.4321")).toBeVisible();
    expect(screen.getByText("12 calls")).toBeVisible();
    expect(screen.getByText("2 versions in all")).toBeVisible();
    const recent = await screen.findByRole("grid", { name: "Jobs" });
    expect(within(recent).getByRole("row", { name: /Crawl/ })).toBeVisible();
    const jobQueries = calls.filter((call) => call.path === "/v1/jobs").map((call) => call.query);
    expect(jobQueries.some((query) => query.includes("status=running"))).toBe(true);
    expect(jobQueries.some((query) => query.includes("limit=20"))).toBe(true);
  });

  it("says when there are no jobs yet, and shows a number it cannot read as a dash", async () => {
    stubApi({
      "GET /v1/jobs": () => Response.json({ items: [], next_cursor: null }),
      "GET /v1/schemas": () => problem(500, { title: "Internal Server Error" }),
      "GET /v1/usage/llm": () => Response.json(COSTS),
    });
    renderOverview();

    expect(await screen.findByText("No jobs yet")).toBeVisible();
    expect(await screen.findByText("Could not load")).toBeVisible();
  });
});
