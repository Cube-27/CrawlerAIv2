import { vi } from "vite-plus/test";

/** One request a screen sent, as the stubbed API saw it. */
export interface Call {
  method: string;
  path: string;
  /** The query string, without `?`; empty when there is none. */
  query: string;
  authorization: string | null;
  /** WHATWG HTML §9.2.4: the id an event stream resumes after; absent when the request sent none. */
  lastEventId?: string;
  body: unknown;
}

/** Every playground mode lists its recent runs. */
const JOBS = "GET /v1/jobs";

/** Stubs `fetch` with one reply per `METHOD /path`, which may arrive later; records every request. A playground mode
 * asks `GET /v1/jobs`: unless `replies` names it, it gets no jobs and is not recorded. */
export function stubApi(
  replies: Record<string, (call: Call) => Response | Promise<Response>>,
): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (request: Request) => {
    const url = new URL(request.url);
    const route = `${request.method} ${url.pathname}`;
    if (route === JOBS && !(JOBS in replies))
      return Response.json({ items: [], next_cursor: null });
    const text = await request.text();
    const call: Call = {
      method: request.method,
      path: url.pathname,
      query: url.search.slice(1),
      authorization: request.headers.get("Authorization"),
      body: text === "" ? null : (JSON.parse(text) as unknown),
    };
    const lastEventId = request.headers.get("Last-Event-ID");
    if (lastEventId !== null) call.lastEventId = lastEventId;
    calls.push(call);
    const reply = replies[`${request.method} ${url.pathname}`];
    if (reply === undefined) throw new Error(`unexpected ${request.method} ${url.pathname}`);
    return reply(call);
  });
  return calls;
}

/** An RFC 9457 problem answer. */
export function problem(
  status: number,
  body: object,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify({ status, ...body }), {
    status,
    headers: { "content-type": "application/problem+json", ...headers },
  });
}

/** A `text/event-stream` answer (WHATWG HTML §9.2) carrying `events`, each `[id, kind, data]`; a null id is left out. */
export function sse(...events: [string | null, string, object][]): Response {
  const text = events
    .map(
      ([id, kind, data]) =>
        `${id === null ? "" : `id: ${id}\n`}event: ${kind}\ndata: ${JSON.stringify(data)}\n\n`,
    )
    .join("");
  return new Response(text, { headers: { "content-type": "text/event-stream" } });
}
