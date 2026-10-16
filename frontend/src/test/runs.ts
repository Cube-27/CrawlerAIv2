import type { JobKind, JobSummary, JsonValuesItem, JsonValuesPage } from "../api/jobs";
import { stubApi, type Call } from "./api";
import { jobSummary } from "./jobs";

/** The API stubs the job-running playground modes share (Batch, Crawl, Extract): the toolbar's schema list, the
 * submit, and the run's job, request, events and `json_values` results (SPEC-10 §4.2–4.6, SPEC-14 §4.4). */

/** The stored schema the toolbar offers: a detail-page schema with one text field. */
export const SCHEMA_ID = "0192a000-0000-7000-8000-0000000000s1";

/** `GET /v1/schemas`: the one stored schema. */
export function schemaList(): Response {
  return Response.json({
    items: [
      {
        id: SCHEMA_ID,
        name: "item_detail",
        origin: "user",
        status: "active",
        page_kind: "detail",
        fields: { title: { type: "text" } },
      },
    ],
  });
}

/** An event stream that stays open and sends nothing. */
export function quietEvents(): Response {
  return new Response(new ReadableStream(), { headers: { "content-type": "text/event-stream" } });
}

/** A page of `json_values` results. */
export function valuesPage(items: JsonValuesItem[], next_cursor: string | null = null): Response {
  return Response.json({ format: "json_values", items, next_cursor } satisfies JsonValuesPage);
}

export interface RunStub {
  /** The submit route, such as `POST /v1/crawl`; it answers `202` with the job's id. */
  submit: string;
  jobId: string;
  kind: JobKind;
  /** The job's summary; by default `jobSummary` of `kind`. */
  job?: JobSummary;
  /** The job's stored request (`GET /v1/jobs/{id}/request`). */
  request?: object;
  /** The job's results, one page. */
  items?: JsonValuesItem[];
}

/** Stubs a mode's run as `run` describes, with `replies` over these defaults; returns the calls recorded. */
export function runApi(run: RunStub, replies: Parameters<typeof stubApi>[0] = {}): Call[] {
  const job = `/v1/jobs/${run.jobId}`;
  const summary = run.job ?? jobSummary({ id: run.jobId, kind: run.kind });
  return stubApi({
    "GET /v1/schemas": schemaList,
    [run.submit]: () => Response.json({ job_id: run.jobId }, { status: 202 }),
    [`GET ${job}`]: () => Response.json(summary),
    [`GET ${job}/request`]: () => Response.json(run.request ?? {}),
    [`GET ${job}/events`]: quietEvents,
    [`GET ${job}/results`]: () => valuesPage(run.items ?? []),
    ...replies,
  });
}
