import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { JobSummary, JsonValuesItem, JsonValuesPage } from "../../../api/jobs";
import { problem, sse, stubApi, type Call } from "../../../test/api";
import { catchDownloads } from "../../../test/downloads";
import { openOptions, openPlayground, pick, posted, toggleFormats } from "../../../test/playground";

// `fetch` answers the batch, job, results and events endpoints with the shapes SPEC-10 §4.2–4.3 and SPEC-14 §4.4
// define.

const JOB_ID = "0192a000-0000-7000-8000-0000000000b1";
const JOB = `/v1/jobs/${JOB_ID}`;
const SCHEMA_ID = "0192a000-0000-7000-8000-0000000000s1";
const CURSOR = "0192a000-0000-7000-8000-0000000000t2";

function job(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: JOB_ID,
    kind: "batch_scrape",
    status: "running",
    counts: { queued: 1, claimed: 0, done: 2, failed: 0, cancelled: 0 },
    outcomes: {
      extracted: 1,
      partial: 0,
      unchanged: 0,
      links_only: 0,
      blocked: 1,
      shell: 0,
      not_found: 0,
      no_match: 0,
      failed: 0,
    },
    usage: { pages_fetched: 2 },
    llm_cost_usd: 0,
    created_at: "2026-10-15T09:00:00Z",
    started_at: "2026-10-15T09:00:01Z",
    finished_at: null,
    engine_version: "0.0.0",
    webhook_url: null,
    cancel_requested: false,
    ...overrides,
  };
}

const FIRST: JsonValuesItem = {
  url: "https://shop.test/items/1",
  outcome: "extracted",
  records: [{ price: { amount: "19.90", currency: "EUR" }, title: "Blue mug" }],
};
const SECOND: JsonValuesItem = {
  url: "https://shop.test/items/2",
  outcome: "blocked",
  records: [],
};
const THIRD: JsonValuesItem = { url: "https://shop.test/items/3", outcome: null, records: [] };

function valuesPage(items: JsonValuesItem[], next_cursor: string | null = null): Response {
  return Response.json({ format: "json_values", items, next_cursor } satisfies JsonValuesPage);
}

const QUIET = () =>
  new Response(new ReadableStream(), { headers: { "content-type": "text/event-stream" } });

/** The batch API: a POST answers the job's id, and the job's run answers `replies` over these defaults. */
function batchApi(replies: Parameters<typeof stubApi>[0] = {}): Call[] {
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
    "POST /v1/batch/scrape": () => Response.json({ job_id: JOB_ID }),
    [`GET ${JOB}`]: () => Response.json(job()),
    [`GET ${JOB}/events`]: QUIET,
    [`GET ${JOB}/results`]: () => valuesPage([FIRST, SECOND, THIRD]),
    ...replies,
  });
}

async function typeUrls(text: string) {
  await userEvent.type(screen.getByRole("textbox", { name: "URLs" }), text);
}

async function start() {
  await userEvent.click(screen.getByRole("button", { name: "Start batch" }));
}

/** The results table, once it has rows. */
async function pagesGrid() {
  const grid = await screen.findByRole("grid", { name: "Pages" });
  await within(grid).findByText(FIRST.url);
  return grid;
}

function resultQueries(calls: readonly Call[]): string[] {
  return calls.filter(({ path }) => path === `${JOB}/results`).map(({ query }) => query);
}

describe("batch playground: the command bar", () => {
  it("is a mode tab and a sidebar entry at /batch", async () => {
    batchApi();
    await openPlayground("/batch");

    const tab = within(screen.getByRole("navigation", { name: "Mode" })).getByRole("tab", {
      name: "Batch",
    });
    expect(tab).toHaveAttribute("href", "/batch");
    expect(tab).toHaveAttribute("aria-selected", "true");
    expect(
      within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Batch" }),
    ).toHaveAttribute("href", "/batch");
  });

  it("counts the URLs as they are typed, one per line", async () => {
    batchApi();
    await openPlayground("/batch");
    expect(screen.getByText("0 URLs")).toBeInTheDocument();

    await typeUrls("https://shop.test/a{Enter}{Enter}https://shop.test/b");

    expect(screen.getByText("2 URLs")).toBeInTheDocument();
  });

  it("appends a CSV file's URLs to the list, dropping those already listed", async () => {
    batchApi();
    await openPlayground("/batch");
    await typeUrls("https://shop.test/a");
    const csv = new File(
      ['name,url\nA,https://shop.test/a\n"B, C",https://shop.test/b\n'],
      "urls.csv",
      {
        type: "text/csv",
      },
    );

    await userEvent.upload(screen.getByLabelText("CSV file"), csv);

    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "URLs" })).toHaveValue(
        "https://shop.test/a\nhttps://shop.test/b",
      );
    });
    expect(screen.getByText("2 URLs")).toBeInTheDocument();
  });

  it("posts the batch request SPEC-10 defines from the list, toolbar and options", async () => {
    const calls = batchApi();
    await openPlayground("/batch");
    await typeUrls("https://shop.test/a{Enter} https://shop.test/b ");
    await toggleFormats("Links");
    await pick(/Schema/, "item_detail version 2");
    const options = await openOptions();
    await userEvent.type(
      options.getByRole("textbox", { name: "Webhook URL" }),
      "https://hooks.test/done",
    );
    await userEvent.click(options.getByRole("button", { name: "Advanced" }));
    await pick(/Fetch method/, "HTTP");

    await start();

    await pagesGrid();
    expect(posted(calls)).toEqual({
      urls: ["https://shop.test/a", "https://shop.test/b"],
      formats: ["markdown", "links", "records"],
      schema: { id: SCHEMA_ID },
      page_kind: "detail",
      fetch: { method_hint: "http" },
      webhook_url: "https://hooks.test/done",
    });
  });

  it("shows the server's per-field problem in the output and on the list", async () => {
    batchApi({
      "POST /v1/batch/scrape": () =>
        problem(422, {
          type: "validation",
          title: "Invalid request",
          errors: [{ field: "urls", reason: "at most 1000 URLs" }],
        }),
    });
    await openPlayground("/batch");
    await typeUrls("https://shop.test/a");

    await start();

    const output = screen.getByRole("region", { name: "Output" });
    expect(await within(output).findByRole("alert")).toHaveTextContent("urls: at most 1000 URLs");
    expect(screen.getByRole("textbox", { name: "URLs" })).toHaveAttribute("aria-invalid", "true");
  });
});

describe("batch playground: the run", () => {
  it("shows the run on the page: status, counts and a row per page in task order", async () => {
    batchApi();
    await openPlayground("/batch");
    await typeUrls("https://shop.test/a");

    await start();

    const grid = await pagesGrid();
    const rows = within(grid).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("rowheader")[0]?.textContent)).toEqual([
      FIRST.url,
      SECOND.url,
      THIRD.url,
    ]);
    const first = within(rows[0] ?? grid);
    expect(first.getByText("extracted")).toBeInTheDocument();
    expect(first.getByText("1")).toBeInTheDocument();
    expect(within(rows[2] ?? grid).getByText("—")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByRole("grid", { name: "Tasks by outcome" })).toBeInTheDocument();
  });

  it("opens a run from ?job= and asks its results as json_values, with metadata only with Metadata in JSON", async () => {
    const calls = batchApi();
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();
    expect(resultQueries(calls)).toEqual(["format=json_values&limit=20"]);

    const options = await openOptions();
    await userEvent.click(options.getByRole("switch", { name: "Metadata in JSON" }));

    await waitFor(() => {
      expect(resultQueries(calls).at(-1)).toBe("format=json_values&limit=20&include=metadata");
    });
  });

  it("shows a row's item in the drawer", async () => {
    batchApi();
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();

    await userEvent.click(screen.getByRole("button", { name: "JSON of page 1" }));

    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText(FIRST.url)).toBeInTheDocument();
    expect(
      JSON.parse(within(drawer).getByRole("region", { name: "Page JSON" }).textContent),
    ).toEqual(FIRST);
  });

  it("reads the page shown again as tasks end, at most once a second", async () => {
    const calls = batchApi({
      [`GET ${JOB}/events`]: () =>
        sse(
          [
            "1",
            "task_extracted",
            { url: FIRST.url, outcome: "extracted", mode: "config", llm_calls: 0 },
          ],
          ["2", "task_failed", { url: SECOND.url, attempts: 3, last_error: "timeout" }],
          [
            "3",
            "task_extracted",
            { url: THIRD.url, outcome: "extracted", mode: "config", llm_calls: 0 },
          ],
          ["4", "completed", {}],
        ),
    });
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();

    await waitFor(() => {
      expect(resultQueries(calls).length).toBeGreaterThanOrEqual(2);
    });
    // The first read, one refresh at once, then at most one more within the next second, and the end's.
    expect(resultQueries(calls).length).toBeLessThanOrEqual(4);
  });

  it("downloads every page's item in task order, equal to the drawers' items", async () => {
    const saved = catchDownloads();
    const calls = batchApi({
      [`GET ${JOB}/results`]: ({ query }) => {
        const params = new URLSearchParams(query);
        if (params.get("limit") !== "200") return valuesPage([FIRST, SECOND, THIRD]);
        return params.get("cursor") === null
          ? valuesPage([FIRST, SECOND], CURSOR)
          : valuesPage([THIRD]);
      },
    });
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();

    await userEvent.click(screen.getByRole("button", { name: "Export JSON" }));

    await waitFor(() => {
      expect(saved.map(({ name }) => name)).toEqual([`job-${JOB_ID}.json`]);
    });
    expect(JSON.parse(await (saved[0]?.text ?? Promise.resolve("")))).toEqual([
      FIRST,
      SECOND,
      THIRD,
    ]);
    expect(resultQueries(calls).slice(1)).toEqual([
      "format=json_values&limit=200",
      `format=json_values&limit=200&cursor=${CURSOR}`,
    ]);
  });

  it("downloads the records as the server's CSV export", async () => {
    const saved = catchDownloads();
    batchApi({
      [`GET ${JOB}/results`]: ({ query }) =>
        new URLSearchParams(query).get("format") === "csv_records"
          ? Response.json({
              format: "csv_records",
              content: "title\nBlue mug\n",
              next_cursor: null,
            })
          : valuesPage([FIRST]),
    });
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();

    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    await waitFor(() => {
      expect(saved.map(({ name }) => name)).toEqual([`job-${JOB_ID}.csv`]);
    });
    expect(await saved[0]?.text).toBe("title\nBlue mug\n");
  });

  it("keeps Cancel in place, disabled, once the run has ended", async () => {
    batchApi({ [`GET ${JOB}`]: () => Response.json(job({ status: "completed" })) });
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();

    expect(screen.getByRole("button", { name: "Cancel job" })).toBeDisabled();
  });
});
