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

/** A `/healthz` answer: the API is up and, by default, does not serve the labeling API. */
export function healthReply(evalUi = false): Response {
  return Response.json({ status: "ok", eval_ui: evalUi });
}

const HEALTH = "GET /healthz";

/** Stubs `fetch` with one reply per `METHOD /path`, which may arrive later; records every request. The shell asks
 * `GET /healthz` on every screen: unless `replies` names it, it gets `healthReply()` and is not recorded. */
export function stubApi(
  replies: Record<string, (call: Call) => Response | Promise<Response>>,
): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (request: Request) => {
    const url = new URL(request.url);
    if (`${request.method} ${url.pathname}` === HEALTH && !(HEALTH in replies))
      return healthReply();
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
