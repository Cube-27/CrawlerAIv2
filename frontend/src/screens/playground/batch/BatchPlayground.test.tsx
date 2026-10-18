import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { JobSummary, JsonValuesItem, PageOutput } from "../../../api/jobs";
import type { FetchSummary } from "../../../api/scrape";
import { problem, sse, stubApi, type Call } from "../../../test/api";
import { catchDownloads } from "../../../test/downloads";
import { jobSummary } from "../../../test/jobs";
import { quietEvents, runApi, SCHEMA_ID, valuesPage } from "../../../test/runs";
import {
  closeOptions,
  fill,
  openOptions,
  openPlayground,
  optionsButton,
  pick,
  posted,
  toggleFormats,
} from "../../../test/playground";

// `fetch` answers the batch, job, results and events endpoints with the shapes SPEC-10 §4.2–4.3 and SPEC-14 §4.4
// define.

const JOB_ID = "0192a000-0000-7000-8000-0000000000b1";
const JOB = `/v1/jobs/${JOB_ID}`;
const CURSOR = "0192a000-0000-7000-8000-0000000000t2";

/** The batch's job: three tasks, one extracted, one blocked, one queued. */
function job(overrides: Partial<JobSummary> = {}): JobSummary {
  const summary = jobSummary({ id: JOB_ID, ...overrides });
  return { ...summary, outcomes: { ...summary.outcomes, extracted: 1, blocked: 1 }, ...overrides };
}

const FIRST: JsonValuesItem = {
  url: "https://shop.test/items/1",
  outcome: "extracted",
  records: [{ price: "19.90", currency: "EUR", title: "Blue mug" }],
};
const SECOND: JsonValuesItem = {
  url: "https://shop.test/items/2",
  outcome: "blocked",
  records: [],
};
const THIRD: JsonValuesItem = { url: "https://shop.test/items/3", outcome: null, records: [] };

/** The batch API: a POST answers the job's id, and the job's run answers `replies` over these defaults. */
function batchApi(replies: Parameters<typeof stubApi>[0] = {}): Call[] {
  return runApi(
    {
      submit: "POST /v1/batch/scrape",
      jobId: JOB_ID,
      kind: "batch_scrape",
      job: job(),
      request: { urls: [FIRST.url], formats: ["records"], schema: { id: SCHEMA_ID } },
      items: [FIRST, SECOND, THIRD],
    },
    replies,
  );
}

/** The first page's outputs in a batch without a schema (SPEC-10 §4.2: a format job's results are page outputs). */
const OUTPUT: PageOutput = {
  task_id: "0192a000-0000-7000-8000-0000000000t1",
  url: FIRST.url,
  status: "done",
  outcome: "extracted",
  last_error: null,
  capture_id: null,
  final_url: FIRST.url,
  fetched_at: null,
  markdown: "# Blue mug",
};

/** A batch that asked for markdown only: `json_values` has no records, `format=json` has the page outputs. */
function outputsApi(): Call[] {
  return batchApi({
    [`GET ${JOB}/request`]: () => Response.json({ urls: [FIRST.url], formats: ["markdown"] }),
    [`GET ${JOB}/results`]: ({ query }) =>
      new URLSearchParams(query).get("format") === "json_values"
        ? valuesPage([{ ...FIRST, records: [] }])
        : Response.json({ items: [OUTPUT], next_cursor: null }),
  });
}

async function typeUrls(text: string) {
  await fill(screen.getByRole("textbox", { name: "URLs" }), text);
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

    await typeUrls("https://shop.test/a\n\nhttps://shop.test/b");

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

  it("posts the batch request SPEC-10 defines, with a schema asking for records alone", async () => {
    const calls = batchApi();
    await openPlayground("/batch");
    await typeUrls("https://shop.test/a\n https://shop.test/b ");
    await toggleFormats("Links");
    await pick(/Schema/, "item_detail");
    expect(screen.getByRole("button", { name: /Format/ })).toBeDisabled();
    const options = await openOptions();
    await userEvent.type(
      options.getByRole("textbox", { name: "Webhook URL" }),
      "https://hooks.test/done",
    );
    await pick(/Fetch method/, "HTTP");
    await closeOptions();

    await start();

    await pagesGrid();
    expect(posted(calls)).toEqual({
      urls: ["https://shop.test/a", "https://shop.test/b"],
      formats: ["records"],
      schema: { id: SCHEMA_ID },
      page_kind: "detail",
      fetch: { method_hint: "http" },
      webhook_url: "https://hooks.test/done",
    });
  });

  it("sends the LLM call limit as the batch's budget, and no budget while it is empty, which the field says is the project setting", async () => {
    const calls = batchApi();
    await openPlayground("/batch");
    await typeUrls("https://shop.test/a");
    const options = await openOptions();
    const limit = options.getByRole("textbox", { name: "LLM call limit" });
    expect(limit).toHaveAttribute("placeholder", "Project setting");

    await userEvent.type(limit, "25");
    await closeOptions();
    await start();

    await pagesGrid();
    expect(posted(calls)).toEqual({
      urls: ["https://shop.test/a"],
      formats: ["markdown"],
      schema: null,
      page_kind: null,
      fetch: { method_hint: "auto" },
      budget: { llm_calls: 25 },
    });
  });

  it("sends the minimum confidence as a fraction, and none while it is empty, which the field says publishes everything", async () => {
    const calls = batchApi();
    await openPlayground("/batch");
    await typeUrls("https://shop.test/a");
    const options = await openOptions();
    const minimum = options.getByRole("textbox", { name: "Minimum confidence (%)" });
    expect(minimum).toHaveAttribute("placeholder", "Publish all");

    await userEvent.type(minimum, "90");
    await closeOptions();
    await start();

    await pagesGrid();
    expect(posted(calls)).toEqual({
      urls: ["https://shop.test/a"],
      formats: ["markdown"],
      schema: null,
      page_kind: null,
      fetch: { method_hint: "auto" },
      min_confidence: 0.9,
    });
  });

  it("names a line that is not a web address on the list, and sends nothing", async () => {
    const calls = batchApi();
    await openPlayground("/batch");
    await typeUrls(["https://shop.test/a", "shop dot test"].join("\n"));

    await start();

    const list = screen.getByRole("textbox", { name: "URLs" });
    expect(list).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Line 2 is not a web address: shop dot test")).toBeInTheDocument();
    expect(calls.filter(({ method }) => method === "POST")).toEqual([]);
    expect(screen.queryByRole("dialog", { name: "Options" })).not.toBeInTheDocument();
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
  it("shows the run on the page: status, progress, outcomes and a row per page in task order", async () => {
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
    expect(screen.getByRole("progressbar", { name: "Pages done" })).toHaveAttribute(
      "aria-valuenow",
      "2",
    );
    expect(screen.getByText("2 of 3 pages done")).toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "Outcomes" }))
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["extracted1", "blocked1"]);
  });

  it("opens a run from ?job= and asks its results as json_values, with metadata only with Metadata in JSON", async () => {
    const calls = batchApi();
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();
    expect(resultQueries(calls)).toEqual(["format=json_values&limit=20"]);

    await userEvent.click(screen.getByRole("button", { name: "Edit and re-run" }));
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
    ).toEqual({ price: "19.90", currency: "EUR", title: "Blue mug" });
  });

  it("shows a page's outputs in the drawer when the batch has no schema", async () => {
    outputsApi();
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();

    await userEvent.click(screen.getByRole("button", { name: "JSON of page 1" }));

    const drawer = await screen.findByRole("dialog");
    await waitFor(() => {
      expect(
        JSON.parse(within(drawer).getByRole("region", { name: "Page JSON" }).textContent),
      ).toEqual(OUTPUT);
    });
  });

  it("downloads a batch's page outputs when it has no schema, and has no CSV to export", async () => {
    const saved = catchDownloads();
    outputsApi();
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Export CSV" })).toBeDisabled();
    });

    await userEvent.click(screen.getByRole("button", { name: "Export JSON" }));

    await waitFor(() => {
      expect(saved.map(({ name }) => name)).toEqual([`job-${JOB_ID}.json`]);
    });
    expect(JSON.parse(await (saved[0]?.text ?? Promise.resolve("")))).toEqual([OUTPUT]);
  });

  it("updates an open drawer when the table reads its page again", async () => {
    let push: (text: string) => void = () => undefined;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        push = (text) => {
          controller.enqueue(new TextEncoder().encode(text));
        };
      },
    });
    const done: JsonValuesItem = {
      ...THIRD,
      outcome: "extracted",
      records: [{ title: "Red mug" }],
    };
    let reads = 0;
    batchApi({
      [`GET ${JOB}/events`]: () =>
        new Response(stream, { headers: { "content-type": "text/event-stream" } }),
      [`GET ${JOB}/results`]: () => {
        reads += 1;
        return valuesPage([FIRST, SECOND, reads === 1 ? THIRD : done]);
      },
    });
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();
    await userEvent.click(screen.getByRole("button", { name: "JSON of page 3" }));
    const drawer = await screen.findByRole("dialog");

    push(`id: 1\nevent: task_extracted\ndata: ${JSON.stringify({ url: THIRD.url })}\n\n`);

    await waitFor(() => {
      expect(
        JSON.parse(within(drawer).getByRole("region", { name: "Page JSON" }).textContent),
      ).toEqual({ title: "Red mug" });
    });
  });

  it("reads the page shown again as tasks end, at most once a second", async () => {
    let push: (text: string) => void = () => undefined;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        push = (text) => {
          controller.enqueue(new TextEncoder().encode(text));
        };
      },
    });
    const calls = batchApi({
      [`GET ${JOB}/events`]: () =>
        new Response(stream, { headers: { "content-type": "text/event-stream" } }),
    });
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();
    const ended = (id: string, url: string) =>
      `id: ${id}
event: task_failed
data: ${JSON.stringify({ url, attempts: 1, last_error: null })}

`;

    push(ended("1", FIRST.url));
    await waitFor(() => {
      expect(resultQueries(calls)).toHaveLength(2);
    });
    push(ended("2", SECOND.url) + ended("3", THIRD.url));
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(resultQueries(calls)).toHaveLength(2);

    await waitFor(
      () => {
        expect(resultQueries(calls)).toHaveLength(3);
      },
      { timeout: 2000 },
    );
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

  it("tells a refused export in a toast, leaving the run's summary where it is", async () => {
    batchApi({
      [`GET ${JOB}/results`]: ({ query }) =>
        new URLSearchParams(query).get("format") === "csv_records"
          ? problem(409, { title: "No records", detail: "This job has no schema." })
          : valuesPage([FIRST]),
    });
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();

    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    expect(await screen.findByText("This job has no schema.")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Output" })).queryByRole("alert")).toBeNull();
  });

  it("shows the run's activity, collapsed, as plain-language lines grouped by page, newest first", async () => {
    batchApi({
      [`GET ${JOB}/events`]: () =>
        sse(
          ["1", "task_fetched", { url: FIRST.url, method: "http", block_class: "ok" }],
          ["2", "task_failed", { url: SECOND.url, attempts: 3, last_error: "timeout" }],
          [
            "3",
            "task_extracted",
            { url: FIRST.url, outcome: "extracted", mode: "config", llm_calls: 1 },
          ],
          [null, "progress", { counts: {}, outcomes: {} }],
        ),
    });
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();
    expect(screen.queryByRole("list", { name: "Activity" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Activity" }));

    const feed = screen.getByRole("list", { name: "Activity" });
    await within(feed).findByText("Extracted: extracted (config). Used 1 LLM call.");
    expect(
      within(feed)
        .getAllByRole("list")
        .map((group) => group.getAttribute("aria-label")),
    ).toEqual([FIRST.url, SECOND.url]);
    expect(
      within(within(feed).getByRole("list", { name: FIRST.url }))
        .getAllByRole("listitem")
        .map((line) => line.textContent),
    ).toEqual(["Fetched over HTTP.", "Extracted: extracted (config). Used 1 LLM call."]);
    expect(within(feed).getByText("Failed after 3 attempts: timeout")).toBeInTheDocument();
  });

  it("does not count cancelled pages as done", async () => {
    batchApi({
      [`GET ${JOB}`]: () =>
        Response.json(
          job({
            status: "cancelled",
            counts: { queued: 0, claimed: 0, done: 2, failed: 0, cancelled: 1 },
          }),
        ),
    });
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();

    expect(screen.getByText("2 of 3 pages done, 1 cancelled")).toBeInTheDocument();
  });

  it("keeps Cancel in place, disabled, once the run has ended", async () => {
    batchApi({ [`GET ${JOB}`]: () => Response.json(job({ status: "completed" })) });
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();

    expect(screen.getByRole("button", { name: "Cancel job" })).toBeDisabled();
  });
});

describe("batch playground: runs", () => {
  const OLDER = "0192a000-0000-7000-8000-0000000000b0";

  it("lists the recent batches before any run, each opening its run here", async () => {
    const calls = batchApi({
      "GET /v1/jobs": () =>
        Response.json({
          items: [
            job({
              status: "completed",
              start_url: "https://shop.test/a",
              url_count: null,
              finished_at: "2026-10-14T09:00:13Z",
            }),
            job({ id: OLDER, started_at: null }),
          ],
          next_cursor: null,
        }),
    });
    await openPlayground("/batch");

    const grid = await screen.findByRole("grid", { name: "Recent runs" });
    const rows = within(grid).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      "https://shop.test/a" + "completed" + "Oct 14, 2026, 09:00" + "12s" + "Open",
      "3 URLs" + "running" + "—" + "—" + "Open",
    ]);
    expect(rows[0]).toHaveAttribute("data-href", `/batch?job=${JOB_ID}`);
    expect(calls.find(({ path }) => path === "/v1/jobs")?.query).toBe("kind=batch_scrape&limit=10");
  });

  it("says there are no runs yet, and links every run of the mode on the Jobs screen", async () => {
    batchApi({ "GET /v1/jobs": () => Response.json({ items: [], next_cursor: null }) });
    await openPlayground("/batch");

    expect(await screen.findByText("No runs yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All runs" })).toHaveAttribute(
      "href",
      "/jobs?kind=batch_scrape",
    );
  });

  it("shows a run's request read-only, and edit and re-run starts a new job, keeping the old one", async () => {
    const calls = batchApi({
      [`GET ${JOB}/request`]: () =>
        Response.json({
          urls: ["https://shop.test/a", "https://shop.test/b"],
          formats: ["links", "metadata"],
          schema: null,
          page_kind: "listing",
          fetch: { method_hint: "browser", respect_robots: true, max_rows: 60 },
          budget: { llm_calls: 40 },
          webhook_url: null,
        }),
      "POST /v1/batch/scrape": () => Response.json({ job_id: OLDER }),
      [`GET /v1/jobs/${OLDER}`]: () => Response.json(job({ id: OLDER })),
      [`GET /v1/jobs/${OLDER}/request`]: () => Response.json({ urls: ["https://shop.test/a"] }),
      [`GET /v1/jobs/${OLDER}/events`]: quietEvents,
      [`GET /v1/jobs/${OLDER}/results`]: () => valuesPage([]),
    });
    await openPlayground(`/batch?job=${JOB_ID}`);
    const list = screen.getByRole("textbox", { name: "URLs" });
    await waitFor(() => {
      expect(list).toHaveValue("https://shop.test/a\nhttps://shop.test/b");
    });
    expect(list).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Start batch" })).not.toBeInTheDocument();
    expect(optionsButton()).toHaveAccessibleDescription("Settings changed");
    const options = await openOptions();
    expect(options.getByRole("switch", { name: "Metadata in JSON" })).toBeChecked();
    expect(options.getByRole("switch", { name: "Metadata in JSON" })).toBeDisabled();
    expect(options.getByRole("textbox", { name: "LLM call limit" })).toHaveValue("40");
    expect(options.getByRole("textbox", { name: "Max rows" })).toHaveValue("60");
    await closeOptions();

    await userEvent.click(screen.getByRole("button", { name: "Edit and re-run" }));
    await fill(list, "\nhttps://shop.test/c");
    await start();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Edit and re-run" })).toBeInTheDocument();
    });
    expect(posted(calls)).toEqual({
      urls: ["https://shop.test/a", "https://shop.test/b", "https://shop.test/c"],
      formats: ["links", "metadata"],
      schema: null,
      page_kind: "listing",
      fetch: { method_hint: "browser", max_rows: 60 },
      budget: { llm_calls: 40 },
    });
  });
});

describe("batch playground: how a page was fetched", () => {
  it("shows how a page was fetched in its drawer: each attempt's rung, status, class, challenge and time", async () => {
    const fetch: FetchSummary = {
      method: "browser",
      status_code: 200,
      block_class: "ok",
      adapter: null,
      attempts: [
        {
          method: "http",
          status: 403,
          block_class: "blocked",
          duration_ms: 120,
          steps: [],
          error: null,
          challenge: "structural",
        },
        {
          method: "browser",
          status: 200,
          block_class: "ok",
          duration_ms: 2400,
          steps: [],
          error: null,
        },
      ],
    };
    const calls = batchApi({
      [`GET ${JOB}/results`]: ({ query }) =>
        new URLSearchParams(query).getAll("include").includes("fetch")
          ? valuesPage([{ ...FIRST, fetch }, SECOND, THIRD])
          : valuesPage([FIRST, SECOND, THIRD]),
    });
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();
    // The table does not ask for the attempts; the drawer does.
    expect(resultQueries(calls)).toEqual(["format=json_values&limit=20"]);

    await userEvent.click(screen.getByRole("button", { name: "JSON of page 1" }));

    const drawer = within(await screen.findByRole("dialog"));
    const attempts = await drawer.findByRole("grid", { name: "Fetch attempts" });
    expect(
      within(attempts)
        .getAllByRole("row")
        .slice(1)
        .map((row) => row.textContent),
    ).toEqual(["http403blockedstructural120—", "browser200ok—2400—"]);
    expect(drawer.getByText("Fetched by browser.")).toBeVisible();
    expect(resultQueries(calls).at(-1)).toBe("format=json_values&limit=20&include=fetch");
  });

  it("names the platform adapter in the drawer of a page it read, and shows a page's outputs with their fetch", async () => {
    const fetch: FetchSummary = {
      method: "api",
      status_code: 200,
      block_class: "ok",
      adapter: "board",
      attempts: [
        { method: "api", status: 200, block_class: "ok", duration_ms: 310, steps: [], error: null },
      ],
    };
    batchApi({
      [`GET ${JOB}/request`]: () => Response.json({ urls: [FIRST.url], formats: ["markdown"] }),
      [`GET ${JOB}/results`]: ({ query }) =>
        new URLSearchParams(query).get("format") === "json_values"
          ? valuesPage([{ ...FIRST, records: [] }])
          : Response.json({ items: [{ ...OUTPUT, fetch }], next_cursor: null }),
    });
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();

    await userEvent.click(screen.getByRole("button", { name: "JSON of page 1" }));

    const drawer = within(await screen.findByRole("dialog"));
    expect(await drawer.findByText("Read from the board platform adapter's API.")).toBeVisible();
    expect(drawer.getByRole("grid", { name: "Fetch attempts" })).toBeInTheDocument();
  });

  it("says a blocked page was not reached, with the attempts that were made", async () => {
    const fetch: FetchSummary = {
      method: "http",
      status_code: 403,
      block_class: "blocked",
      adapter: null,
      attempts: [
        {
          method: "http",
          status: 403,
          block_class: "blocked",
          duration_ms: 70,
          steps: [],
          error: null,
          challenge: "structural",
        },
        {
          method: "browser",
          status: 403,
          block_class: "blocked",
          duration_ms: 20300,
          steps: [],
          error: null,
          challenge: "structural",
        },
      ],
    };
    batchApi({
      [`GET ${JOB}/results`]: () => valuesPage([FIRST, { ...SECOND, fetch }, THIRD]),
    });
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();

    await userEvent.click(screen.getByRole("button", { name: "JSON of page 2" }));

    const drawer = within(await screen.findByRole("dialog"));
    expect(await drawer.findByText("Not reached: blocked after 2 attempts.")).toBeVisible();
    expect(
      within(drawer.getByRole("row", { name: "browser" })).getByText("structural"),
    ).toBeVisible();
  });

  it("shows no fetch section for a page whose capture kept no attempts", async () => {
    batchApi();
    await openPlayground(`/batch?job=${JOB_ID}`);
    await pagesGrid();

    await userEvent.click(screen.getByRole("button", { name: "JSON of page 2" }));

    const drawer = within(await screen.findByRole("dialog"));
    expect(drawer.getByText(SECOND.url)).toBeVisible();
    expect(drawer.queryByRole("heading", { name: "Fetch" })).not.toBeInTheDocument();
  });
});
