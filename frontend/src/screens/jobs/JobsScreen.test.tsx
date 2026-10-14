import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vite-plus/test";
import { routes } from "../../app/router";
import type { JobPage, JobSummary, PageOutput, PageOutputPage } from "../../api/jobs";
import type { RecordPage } from "../../api/records";
import type { SchemaDef } from "../../api/schemas";
import { problem, stubApi, type Call } from "../../test/api";
import { recordField } from "../../test/records";
import { connect } from "../../test/connect";

const JOB_ID = "0192a000-0000-7000-8000-000000000901";
const SCHEMA_ID = "0192a000-0000-7000-8000-000000000101";
const RECORD_ID = "0192a000-0000-7000-8000-000000000301";
const TASK_ID = "0192a000-0000-7000-8000-000000000401";
const SECOND_JOB_ID = "0192a000-0000-7000-8000-000000000902";
const JOB = `/v1/jobs/${JOB_ID}`;

function job(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: JOB_ID,
    kind: "batch_scrape",
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
    llm_cost_usd: 0.0123,
    created_at: "2026-10-14T09:00:00Z",
    started_at: "2026-10-14T09:00:01Z",
    finished_at: null,
    engine_version: "0.0.0",
    webhook_url: null,
    cancel_requested: false,
    ...overrides,
  };
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

/** A `text/event-stream` answer (WHATWG HTML §9.2) carrying `events`, each `[id, kind, data]`; a null id is left out. */
function sse(...events: [string | null, string, object][]): Response {
  const text = events
    .map(
      ([id, kind, data]) =>
        `${id === null ? "" : `id: ${id}\n`}event: ${kind}\ndata: ${JSON.stringify(data)}\n\n`,
    )
    .join("");
  return new Response(text, { headers: { "content-type": "text/event-stream" } });
}

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
  await connect();
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
    await open(`/jobs/${JOB_ID}`, "Batch scrape job");

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
    await open(`/jobs/${JOB_ID}`, "Batch scrape job");

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
      () =>
        new Response(new ReadableStream(), { headers: { "content-type": "text/event-stream" } }),
    ];
    jobApi({
      [`GET ${JOB}`]: () => Response.json(job({ status })),
      [`GET ${JOB}/events`]: () => {
        const next = answers.shift();
        if (next === undefined) throw new Error("no more connections expected");
        return next();
      },
    });
    await open(`/jobs/${JOB_ID}`, "Batch scrape job");

    expect(await eventLog().findByText("live", {}, { timeout: 3000 })).toBeInTheDocument();
    await waitFor(() => {
      expect(jobStatus()).toHaveTextContent("completed");
    });
  });

  it("shows the problem of a refused event stream", async () => {
    jobApi({
      [`GET ${JOB}/events`]: () => problem(404, { title: "Not found", detail: `no job ${JOB_ID}` }),
    });
    await open(`/jobs/${JOB_ID}`, "Batch scrape job");

    expect(await eventLog().findByText(`no job ${JOB_ID}`)).toBeInTheDocument();
    expect(eventLog().getByText("failed")).toBeInTheDocument();
  });

  it("lists the pages of a job without a schema", async () => {
    jobApi({ [`GET ${JOB}/results`]: () => Response.json(pages) });
    await open(`/jobs/${JOB_ID}`, "Batch scrape job");

    const grid = await screen.findByRole("grid", { name: "Pages" });
    expect(rowsOf(grid)).toEqual([
      "https://shop.example.test/item/1doneextracted—Oct 14, 2026, 09:00",
    ]);
  });

  it("shows why a page failed or was blocked, in full on hover", async () => {
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
    await open(`/jobs/${JOB_ID}`, "Batch scrape job");

    const grid = await screen.findByRole("grid", { name: "Pages" });
    expect(within(grid).getByRole("columnheader", { name: "Reason" })).toBeInTheDocument();
    expect(rowsOf(grid)).toEqual([
      `https://shop.example.test/item/1failedfailed${reason}—`,
      "https://shop.example.test/item/2doneblockedrobots—",
    ]);
    await userEvent.hover(within(grid).getByRole("button", { name: reason }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(reason);
  });

  it("shows a task's failure in the event log, its data in full on hover", async () => {
    const failed = {
      task_id: TASK_ID,
      url: "https://shop.example.test/item/1",
      attempts: 3,
      last_error: "lease expired",
    };
    jobApi({
      [`GET ${JOB}/events`]: () => sse(["1", "task_failed", failed], ["2", "failed", {}]),
    });
    await open(`/jobs/${JOB_ID}`, "Batch scrape job");

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
    const saved: { name: string; text: Promise<string> }[] = [];
    const blobs = new Map<string, Blob>();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: (blob: Blob) => {
        const url = `blob:${String(blobs.size)}`;
        blobs.set(url, blob);
        return url;
      },
    });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: () => undefined });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      saved.push({
        name: this.download,
        text: blobs.get(this.href)?.text() ?? Promise.resolve(""),
      });
    });
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
    await open(`/jobs/${JOB_ID}`, "Batch scrape job");

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
    await open(`/jobs/${JOB_ID}`, "Batch scrape job");

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
    await open(`/jobs/${JOB_ID}`, "Batch scrape job");
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
    await open(`/jobs/${JOB_ID}`, "Batch scrape job");

    expect(jobStatus()).toHaveTextContent("cancelled");
    expect(jobStatus()).not.toHaveTextContent("cancel requested");
  });
});

describe("Jobs screen", () => {
  it("queues a batch from its dialog and opens the new job", async () => {
    const calls = jobApi({
      "POST /v1/batch/scrape": () => Response.json({ job_id: JOB_ID }, { status: 202 }),
    });
    await open("/jobs", "Jobs");

    await userEvent.click(screen.getByRole("button", { name: "New batch" }));
    const dialog = within(await screen.findByRole("dialog"));
    await userEvent.type(
      dialog.getByLabelText("URLs"),
      "https://shop.example.test/item/1{Enter}https://shop.example.test/item/2",
    );
    await userEvent.click(dialog.getByRole("button", { name: "Queue batch" }));

    await screen.findByRole("heading", { level: 1, name: "Batch scrape job" });
    expect(calls.find(({ path }) => path === "/v1/batch/scrape")?.body).toEqual({
      urls: ["https://shop.example.test/item/1", "https://shop.example.test/item/2"],
      formats: ["markdown"],
      schema: null,
      page_kind: null,
      fetch: { method_hint: "auto" },
    });
  });

  it("offers detail pages only for a batch's records, which the server refuses for listing pages", async () => {
    jobApi();
    await open("/jobs", "Jobs");
    await userEvent.click(screen.getByRole("button", { name: "New batch" }));
    const dialog = within(await screen.findByRole("dialog"));
    await userEvent.click(
      within(dialog.getByRole("radiogroup", { name: "Page kind" })).getByLabelText("Listing"),
    );

    await userEvent.click(dialog.getByRole("checkbox", { name: "Records" }));

    const kinds = within(dialog.getByRole("radiogroup", { name: "Page kind" }));
    expect(kinds.getByLabelText("Listing")).toBeDisabled();
    expect(kinds.getByLabelText("Listing")).not.toBeChecked();
    expect(dialog.getByText("Records of listing pages are not available yet.")).toBeInTheDocument();
  });

  it("shows a refused batch's problem with the member it names", async () => {
    jobApi({
      "POST /v1/batch/scrape": () =>
        problem(422, {
          title: "Invalid request",
          errors: [{ field: "urls.0", reason: "the target is not allowed" }],
        }),
    });
    await open("/jobs", "Jobs");

    await userEvent.click(screen.getByRole("button", { name: "New batch" }));
    const dialog = within(await screen.findByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("URLs"), "https://shop.example.test/item/1");
    await userEvent.click(dialog.getByRole("button", { name: "Queue batch" }));

    expect(await dialog.findByText("Invalid request")).toBeInTheDocument();
    expect(dialog.getByText("urls.0: the target is not allowed")).toBeInTheDocument();
  });

  it("queues a crawl with a page-kind rule", async () => {
    const calls = jobApi({
      "POST /v1/crawl": () => Response.json({ job_id: JOB_ID }, { status: 202 }),
    });
    await open("/jobs", "Jobs");

    await userEvent.click(screen.getByRole("button", { name: "New crawl" }));
    const dialog = within(await screen.findByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Start URL"), "https://shop.example.test/");
    await userEvent.click(dialog.getByRole("button", { name: "Add rule" }));
    await userEvent.type(dialog.getByLabelText("Pattern 1"), "https://shop.example.test/item/*");
    await userEvent.click(
      within(dialog.getByRole("radiogroup", { name: "Page kind 1" })).getByLabelText("Listing"),
    );
    await userEvent.click(dialog.getByRole("button", { name: "Queue crawl" }));

    await screen.findByRole("heading", { level: 1, name: "Batch scrape job" });
    expect(calls.find(({ path }) => path === "/v1/crawl")?.body).toEqual({
      url: "https://shop.example.test/",
      formats: ["markdown"],
      schema: null,
      page_kind_rules: [{ pattern: "https://shop.example.test/item/*", page_kind: "listing" }],
      include: [],
      exclude: [],
      fetch: { method_hint: "auto" },
    });
  });

  it("queues an extract with a prompt and opens the new job", async () => {
    const calls = jobApi({
      "POST /v1/extract": () =>
        Response.json(
          { job_id: JOB_ID, schema: { ...schema, origin: "prompt_draft" } },
          { status: 202 },
        ),
      [`GET ${JOB}`]: () => Response.json(job({ kind: "extract" })),
    });
    await open("/jobs", "Jobs");

    await userEvent.click(screen.getByRole("button", { name: "New extract" }));
    const dialog = within(await screen.findByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("URLs"), "https://shop.example.test/item/*");
    await userEvent.click(dialog.getByLabelText("From a prompt"));
    await userEvent.type(dialog.getByLabelText("Prompt"), "title and price");
    await userEvent.click(dialog.getByLabelText("Detail"));
    await userEvent.click(dialog.getByRole("button", { name: "Queue extract" }));

    await screen.findByRole("heading", { level: 1, name: "Extract job" });
    expect(calls.find(({ path }) => path === "/v1/extract")?.body).toEqual({
      urls: ["https://shop.example.test/item/*"],
      schema: { prompt: "title and price" },
      page_kind: "detail",
      fetch: { method_hint: "auto" },
    });
  });

  it("maps a site and lists the URLs found", async () => {
    const calls = jobApi({
      "POST /v1/map": () =>
        Response.json({
          urls: ["https://shop.example.test/item/1", "https://shop.example.test/item/2"],
          sources: { sitemap: 2, links: 0 },
          truncated: true,
        }),
    });
    await open("/jobs", "Jobs");

    await userEvent.click(screen.getByRole("button", { name: "Map URLs" }));
    const dialog = within(await screen.findByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("URL"), "https://shop.example.test/");
    await userEvent.click(dialog.getByRole("button", { name: "Map" }));

    expect(await dialog.findByLabelText("URLs found")).toHaveValue(
      "https://shop.example.test/item/1\nhttps://shop.example.test/item/2",
    );
    expect(dialog.getByText("2 URLs: 2 from sitemaps, 0 from links.")).toBeInTheDocument();
    expect(dialog.getByText("The list is cut short.")).toBeInTheDocument();
    expect(calls.find(({ path }) => path === "/v1/map")?.body).toEqual({
      url: "https://shop.example.test/",
      include: [],
      exclude: [],
      use_sitemaps: true,
      use_links: true,
    });
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
      "Batch scrape" + "running" + "3 tasks: 1 queued, 2 done" + "Oct 14, 2026, 09:00",
      "Crawl" + "failed" + "4 tasks: 3 failed, 1 cancelled" + "Oct 13, 2026, 08:00",
    ]);
  });

  it("opens a job from its row", async () => {
    jobApi({ "GET /v1/jobs": jobPage([job()]) });
    await open("/jobs", "Jobs");

    const table = await screen.findByRole("grid", { name: "Jobs" });
    await userEvent.click(within(table).getByText("Batch scrape"));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Batch scrape job" }),
    ).toBeInTheDocument();
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

    expect(
      await screen.findByRole("heading", { level: 1, name: "Batch scrape job" }),
    ).toBeInTheDocument();
  });
});
