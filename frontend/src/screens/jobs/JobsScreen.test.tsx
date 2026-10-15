import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vite-plus/test";
import { routes } from "../../app/router";
import type { JobPage, JobSummary, PageOutput, PageOutputPage } from "../../api/jobs";
import type { RecordPage } from "../../api/records";
import type { SchemaDef } from "../../api/schemas";
import { problem, sse, stubApi, type Call } from "../../test/api";
import { catchDownloads } from "../../test/downloads";
import { jobSummary } from "../../test/jobs";
import { stubTextLayout } from "../../test/layout";
import { quietEvents, valuesPage } from "../../test/runs";
import { recordField } from "../../test/records";

const JOB_ID = "0192a000-0000-7000-8000-000000000901";
const SCHEMA_ID = "0192a000-0000-7000-8000-000000000101";
const RECORD_ID = "0192a000-0000-7000-8000-000000000301";
const TASK_ID = "0192a000-0000-7000-8000-000000000401";
const SECOND_JOB_ID = "0192a000-0000-7000-8000-000000000902";
const JOB = `/v1/jobs/${JOB_ID}`;

/** A `learn` job: no playground mode runs it, so it keeps its job page (SPEC-14 §4.8). */
function job(overrides: Partial<JobSummary> = {}): JobSummary {
  return jobSummary({ id: JOB_ID, kind: "learn", ...overrides });
}

const schema: SchemaDef = {
  id: SCHEMA_ID,
  name: "item_detail",
  version: 1,
  origin: "user",
  status: "active",
  page_kind: "detail",
  required_groups: [["title"]],
  fields: { title: { type: "text", required: true, scope: "row" } },
};

const records: RecordPage = {
  items: [
    {
      id: RECORD_ID,
      schema_id: SCHEMA_ID,
      capture_id: null,
      mode: "adhoc",
      version: 1,
      complete: true,
      confidence: 0.97,
      changed_fields: [],
      fields: { title: recordField({ value: "Blue kettle" }) },
    },
  ],
  next_cursor: null,
};

const page: PageOutput = {
  task_id: TASK_ID,
  url: "https://shop.example.test/item/1",
  status: "done",
  outcome: "extracted",
  last_error: null,
  capture_id: null,
  final_url: "https://shop.example.test/item/1",
  fetched_at: "2026-10-14T09:00:02Z",
};

const pages: PageOutputPage = { items: [page], next_cursor: null };

const ENDED = () =>
  sse(
    ["1", "task_fetched", { url: "https://shop.example.test/item/1" }],
    [null, "progress", {}],
    ["2", "completed", {}],
  );

/** A `GET /v1/jobs` answer. */
function jobPage(items: JobSummary[], next_cursor: string | null = null) {
  return () => Response.json({ items, next_cursor } satisfies JobPage);
}

/** The jobs table, once it shows rows. */
function findJobsGrid(): Promise<HTMLElement> {
  return screen.findByRole("grid", { name: "Jobs" });
}

/** The query of each `GET /v1/jobs` the screen sent, in order. */
function listQueries(calls: Call[]): string[] {
  return calls.filter(({ path }) => path === "/v1/jobs").map(({ query }) => query);
}

function jobApi(extra: Record<string, (call: Call) => Response> = {}) {
  return stubApi({
    "GET /v1/jobs": jobPage([]),
    [`GET ${JOB}`]: () => Response.json(job()),
    [`GET ${JOB}/events`]: ENDED,
    [`GET ${JOB}/results`]: () => Response.json(records),
    [`GET /v1/schemas/${SCHEMA_ID}`]: () => Response.json(schema),
    ...extra,
  });
}

async function open(path: string, heading: string) {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
  await screen.findByRole("heading", { level: 1, name: heading });
}

/** The event log's section: its stream state, problem and table. */
function eventLog() {
  return within(screen.getByRole("region", { name: "Events" }));
}

/** The job's status, beside the page title. */
function jobStatus(): HTMLElement | null {
  return screen.getByRole("heading", { level: 1 }).parentElement;
}

function rowsOf(grid: HTMLElement): (string | null)[] {
  return within(grid)
    .getAllByRole("row")
    .slice(1)
    .map((row) => row.textContent);
}

afterEach(() => {
  vi.useRealTimers();
});

describe("Job screen", () => {
  it("shows the job's status, task counts, usage, events and records", async () => {
    jobApi();
    await open(`/jobs/${JOB_ID}`, "Learn job");

    expect(jobStatus()).toHaveTextContent("running");
    expect(rowsOf(screen.getByRole("grid", { name: "Tasks by outcome" }))).toEqual(["extracted2"]);
    expect(rowsOf(screen.getByRole("grid", { name: "Usage" }))).toEqual(["pages_fetched2"]);
    expect(screen.getByText("Estimated LLM cost: $0.0123")).toBeInTheDocument();
    const events = screen.getByRole("grid", { name: "Events" });
    await waitFor(() => {
      expect(rowsOf(events)).toEqual([
        'task_fetched1{"url":"https://shop.example.test/item/1"}',
        "completed2{}",
      ]);
    });
    expect(eventLog().getByText("ended")).toBeInTheDocument();
    const results = await screen.findByRole("grid", { name: "Records" });
    expect(within(results).getByText("Blue kettle")).toBeInTheDocument();
  });

  it("reconnects a dropped event stream after the last event id it received", async () => {
    const answers = [
      () => sse(["1", "task_fetched", { url: "https://shop.example.test/item/1" }]),
      () => sse(["2", "completed", {}]),
    ];
    const calls = jobApi({
      [`GET ${JOB}/events`]: () => {
        const next = answers.shift();
        if (next === undefined) throw new Error("no more connections expected");
        return next();
      },
    });
    await open(`/jobs/${JOB_ID}`, "Learn job");

    expect(await eventLog().findByText("reconnecting")).toBeInTheDocument();
    expect(await eventLog().findByText("ended", {}, { timeout: 3000 })).toBeInTheDocument();
    const streams = calls.filter(({ path }) => path === `${JOB}/events`);
    expect(streams.map(({ lastEventId }) => lastEventId)).toEqual([undefined, "1"]);
    expect(rowsOf(screen.getByRole("grid", { name: "Events" }))).toEqual([
      'task_fetched1{"url":"https://shop.example.test/item/1"}',
      "completed2{}",
    ]);
  });

  it("reads the job again when a dropped stream reconnects, so an end missed while away shows", async () => {
    let status: JobSummary["status"] = "running";
    const answers = [
      () => {
        status = "completed";
        return sse(["1", "task_fetched", { url: "https://shop.example.test/item/1" }]);
      },
      // The second connection opens and stays quiet: the job ended while the stream was away.
      quietEvents,
    ];
    jobApi({
      [`GET ${JOB}`]: () => Response.json(job({ status })),
      [`GET ${JOB}/events`]: () => {
        const next = answers.shift();
        if (next === undefined) throw new Error("no more connections expected");
        return next();
      },
    });
    await open(`/jobs/${JOB_ID}`, "Learn job");

    expect(await eventLog().findByText("live", {}, { timeout: 3000 })).toBeInTheDocument();
    await waitFor(() => {
      expect(jobStatus()).toHaveTextContent("completed");
    });
  });

  it("shows the problem of a refused event stream", async () => {
    jobApi({
      [`GET ${JOB}/events`]: () => problem(404, { title: "Not found", detail: `no job ${JOB_ID}` }),
    });
    await open(`/jobs/${JOB_ID}`, "Learn job");

    expect(await eventLog().findByText(`no job ${JOB_ID}`)).toBeInTheDocument();
    expect(eventLog().getByText("failed")).toBeInTheDocument();
  });

  it("lists the pages of a job without a schema", async () => {
    jobApi({ [`GET ${JOB}/results`]: () => Response.json(pages) });
    await open(`/jobs/${JOB_ID}`, "Learn job");

    const grid = await screen.findByRole("grid", { name: "Pages" });
    expect(rowsOf(grid)).toEqual([
      "https://shop.example.test/item/1doneextracted—Oct 14, 2026, 09:00",
    ]);
  });

  it("shows why a page failed or was blocked, in full on hover", async () => {
    stubTextLayout();
    const reason = `budget_exhausted:${" the job's budget ran out before this page".repeat(4)}`;
    const failing: PageOutputPage = {
      items: [
        {
          ...page,
          status: "failed",
          outcome: "failed",
          last_error: reason,
          final_url: null,
          fetched_at: null,
        },
        {
          ...page,
          task_id: "0192a000-0000-7000-8000-000000000402",
          url: "https://shop.example.test/item/2",
          outcome: "blocked",
          last_error: "robots",
          final_url: null,
          fetched_at: null,
        },
      ],
      next_cursor: null,
    };
    jobApi({ [`GET ${JOB}/results`]: () => Response.json(failing) });
    await open(`/jobs/${JOB_ID}`, "Learn job");

    const grid = await screen.findByRole("grid", { name: "Pages" });
    expect(within(grid).getByRole("columnheader", { name: "Reason" })).toBeInTheDocument();
    expect(rowsOf(grid)).toEqual([
      `https://shop.example.test/item/1failedfailed${reason}—`,
      "https://shop.example.test/item/2doneblockedrobots—",
    ]);
    // React Aria opens a tooltip on hover only while the pointer is the interaction modality, which a press sets.
    await userEvent.click(screen.getByRole("heading", { level: 1 }));
    await userEvent.hover(within(grid).getByRole("button", { name: reason }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(reason);
  });

  it("shows a task's failure in the event log, its data in full on hover", async () => {
    stubTextLayout();
    const failed = {
      task_id: TASK_ID,
      url: "https://shop.example.test/item/1",
      attempts: 3,
      last_error: "lease expired",
    };
    jobApi({
      [`GET ${JOB}/events`]: () => sse(["1", "task_failed", failed], ["2", "failed", {}]),
    });
    await open(`/jobs/${JOB_ID}`, "Learn job");

    const data = JSON.stringify(failed);
    await waitFor(() => {
      expect(rowsOf(screen.getByRole("grid", { name: "Events" }))).toEqual([
        `task_failed1${data}`,
        "failed2{}",
      ]);
    });
    await userEvent.hover(eventLog().getByRole("button", { name: data }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(data);
  });

  it("exports every page of the records as CSV files", async () => {
    const saved = catchDownloads();
    const calls = jobApi({
      [`GET ${JOB}/results`]: ({ query }) => {
        const params = new URLSearchParams(query);
        if (params.get("format") !== "csv_records") return Response.json(records);
        const first = params.get("cursor") === null;
        return Response.json({
          format: "csv_records",
          content: first ? "title\nBlue kettle\n" : "title\nRed kettle\n",
          next_cursor: first ? RECORD_ID : null,
        });
      },
    });
    await open(`/jobs/${JOB_ID}`, "Learn job");

    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    await screen.findByText(`Saved job-${JOB_ID}-1.csv, job-${JOB_ID}-2.csv.`);
    expect(await Promise.all(saved.map(async ({ name, text }) => [name, await text]))).toEqual([
      [`job-${JOB_ID}-1.csv`, "title\nBlue kettle\n"],
      [`job-${JOB_ID}-2.csv`, "title\nRed kettle\n"],
    ]);
    const exports = calls.filter(({ query }) => query.includes("csv_records"));
    expect(exports.map(({ query }) => query)).toEqual([
      "format=csv_records&limit=200",
      `format=csv_records&limit=200&cursor=${RECORD_ID}`,
    ]);
  });

  it("cancels the job after confirmation and shows its new status", async () => {
    const calls = jobApi({
      [`DELETE ${JOB}`]: () => Response.json(job({ status: "cancelled" })),
    });
    await open(`/jobs/${JOB_ID}`, "Learn job");

    await userEvent.click(screen.getByRole("button", { name: "Cancel job" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel job" }));

    await waitFor(() => {
      expect(jobStatus()).toHaveTextContent("cancelled");
    });
    expect(calls.filter(({ method }) => method === "DELETE")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Cancel job" })).not.toBeInTheDocument();
  });

  it("shows a running job's requested cancel until the job ends", async () => {
    jobApi({
      [`DELETE ${JOB}`]: () => Response.json(job({ cancel_requested: true })),
    });
    await open(`/jobs/${JOB_ID}`, "Learn job");
    expect(jobStatus()).not.toHaveTextContent("cancel requested");

    await userEvent.click(screen.getByRole("button", { name: "Cancel job" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel job" }));

    await waitFor(() => {
      expect(jobStatus()).toHaveTextContent("runningcancel requested");
    });
    expect(screen.queryByRole("button", { name: "Cancel job" })).not.toBeInTheDocument();
  });

  it("drops the requested cancel once the job has ended", async () => {
    jobApi({
      [`GET ${JOB}`]: () => Response.json(job({ status: "cancelled", cancel_requested: true })),
    });
    await open(`/jobs/${JOB_ID}`, "Learn job");

    expect(jobStatus()).toHaveTextContent("cancelled");
    expect(jobStatus()).not.toHaveTextContent("cancel requested");
  });
});

describe("Jobs screen", () => {
  it("is run history: it starts no job", async () => {
    jobApi();
    await open("/jobs", "Jobs");

    expect(
      screen.getByText("Every run, newest first. A run opens in its playground mode."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /New|Map URLs/ })).not.toBeInTheDocument();
  });

  it("redirects a run's job page to its run in its mode", async () => {
    jobApi({
      [`GET ${JOB}`]: () => Response.json(job({ kind: "batch_scrape" })),
      [`GET ${JOB}/results`]: () => valuesPage([]),
      "GET /v1/schemas": () => Response.json({ items: [] }),
    });
    await open(`/jobs/${JOB_ID}`, "Playground");

    const batch = within(screen.getByRole("navigation", { name: "Mode" })).getByRole("tab", {
      name: "Batch",
    });
    expect(batch).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("grid", { name: "Pages" })).toBeInTheDocument();
  });
});

describe("Jobs table", () => {
  it("lists the jobs with their kind, status, task counts and creation time", async () => {
    jobApi({
      "GET /v1/jobs": jobPage([
        job(),
        job({
          id: SECOND_JOB_ID,
          kind: "crawl",
          status: "failed",
          counts: { queued: 0, claimed: 0, done: 0, failed: 3, cancelled: 1 },
          created_at: "2026-10-13T08:00:00Z",
        }),
      ]),
    });
    await open("/jobs", "Jobs");

    const table = await screen.findByRole("grid", { name: "Jobs" });
    expect(rowsOf(table)).toEqual([
      "Learn" + "running" + "3 tasks: 1 queued, 2 done" + "Oct 14, 2026, 09:00",
      "Crawl" + "failed" + "4 tasks: 3 failed, 1 cancelled" + "Oct 13, 2026, 08:00",
    ]);
  });

  it("links a run's row to its playground mode, and a learn job's row to its job page", async () => {
    jobApi({ "GET /v1/jobs": jobPage([job({ id: SECOND_JOB_ID, kind: "crawl" }), job()]) });
    await open("/jobs", "Jobs");

    const table = await screen.findByRole("grid", { name: "Jobs" });
    const [crawl, learn] = within(table).getAllByRole("row").slice(1);
    expect(crawl).toHaveAttribute("data-href", `/crawl?job=${SECOND_JOB_ID}`);
    expect(learn).toHaveAttribute("data-href", `/jobs/${JOB_ID}`);
  });

  it("opens a job from its row", async () => {
    jobApi({ "GET /v1/jobs": jobPage([job()]) });
    await open("/jobs", "Jobs");

    const table = await screen.findByRole("grid", { name: "Jobs" });
    await userEvent.click(within(table).getByText("Learn"));

    expect(await screen.findByRole("heading", { level: 1, name: "Learn job" })).toBeInTheDocument();
  });

  it("pages forward with the cursor the API returned, and back to the first page", async () => {
    const calls = jobApi({
      "GET /v1/jobs": (call) =>
        call.query.includes("cursor=c2")
          ? jobPage([job({ id: SECOND_JOB_ID, kind: "map" })])()
          : jobPage([job()], "c2")(),
    });
    await open("/jobs", "Jobs");
    await screen.findByRole("grid", { name: "Jobs" });
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await within(await findJobsGrid()).findByText("Map")).toBeInTheDocument();
    expect(screen.getByText("Page 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(await screen.findByText("Page 1")).toBeInTheDocument();
    expect(listQueries(calls)).toEqual(["limit=20", "cursor=c2&limit=20", "limit=20"]);
  });

  it("keeps the pager in place while the next page loads", async () => {
    const gate: { release: () => void } = { release: () => undefined };
    const pending = new Promise<void>((resolve) => {
      gate.release = resolve;
    });
    jobApi({
      "GET /v1/jobs": (call) =>
        call.query.includes("cursor=c2")
          ? jobPage([job({ id: SECOND_JOB_ID, kind: "map" })])()
          : jobPage([job()], "c2")(),
    });
    // The second page answers only when released, so its loading state can be seen.
    const fetchStub = globalThis.fetch;
    vi.stubGlobal("fetch", async (request: Request) => {
      if (request.url.includes("cursor=c2")) await pending;
      return fetchStub(request);
    });
    await open("/jobs", "Jobs");
    await screen.findByRole("grid", { name: "Jobs" });

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByLabelText("Loading jobs")).toBeInTheDocument();
    expect(screen.getByText("Page 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

    gate.release();
    expect(await within(await findJobsGrid()).findByText("Map")).toBeInTheDocument();
  });

  it("filters the jobs by kind and status, from the first page", async () => {
    const calls = jobApi({
      "GET /v1/jobs": (call) =>
        call.query.includes("kind=crawl")
          ? jobPage([job({ id: SECOND_JOB_ID, kind: "crawl", status: "failed" })])()
          : jobPage([job()], "c2")(),
    });
    await open("/jobs", "Jobs");
    await screen.findByRole("grid", { name: "Jobs" });
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Page 2");

    await userEvent.click(screen.getByRole("button", { name: /Kind/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Crawl" }));
    await userEvent.click(screen.getByRole("button", { name: /Status/ }));
    await userEvent.click(await screen.findByRole("option", { name: "failed" }));

    await waitFor(() => {
      expect(rowsOf(screen.getByRole("grid", { name: "Jobs" }))).toEqual([
        "Crawl" + "failed" + "3 tasks: 1 queued, 2 done" + "Oct 14, 2026, 09:00",
      ]);
    });
    expect(screen.getByText("Page 1")).toBeInTheDocument();
    expect(listQueries(calls).at(-1)).toBe("kind=crawl&status=failed&limit=20");
  });

  it("reads the filters from the address, so going back to the list keeps them", async () => {
    const calls = jobApi({ "GET /v1/jobs": jobPage([job({ status: "failed" })]) });
    await open("/jobs?status=failed", "Jobs");
    await findJobsGrid();

    expect(listQueries(calls)).toEqual(["status=failed&limit=20"]);
    expect(screen.getByRole("button", { name: /Status/ })).toHaveTextContent("failed");
  });

  it("says when no job matches the filters", async () => {
    jobApi({
      "GET /v1/jobs": (call) => jobPage(call.query.includes("status=") ? [] : [job()])(),
    });
    await open("/jobs", "Jobs");
    await screen.findByRole("grid", { name: "Jobs" });

    await userEvent.click(screen.getByRole("button", { name: /Status/ }));
    await userEvent.click(await screen.findByRole("option", { name: "cancelled" }));

    expect(await screen.findByText("No job matches these filters")).toBeInTheDocument();
  });

  it("says when there are no jobs yet", async () => {
    jobApi();
    await open("/jobs", "Jobs");

    expect(await screen.findByText("No jobs yet")).toBeInTheDocument();
  });

  it("shows the problem of a refused list", async () => {
    jobApi({ "GET /v1/jobs": () => problem(503, { title: "Database unavailable" }) });
    await open("/jobs", "Jobs");

    expect(await screen.findByText("Database unavailable")).toBeInTheDocument();
  });

  it("opens a job by its id", async () => {
    jobApi();
    await open("/jobs", "Jobs");

    await userEvent.type(screen.getByLabelText("Job ID"), JOB_ID);
    await userEvent.click(screen.getByRole("button", { name: "Open job" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Learn job" })).toBeInTheDocument();
  });
});
