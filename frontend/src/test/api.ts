import { vi } from "vite-plus/test";

/** One request a screen sent, as the stubbed API saw it. */
interface Call {
  method: string;
  path: string;
  /** The query string, without `?`; empty when there is none. */
  query: string;
  authorization: string | null;
  body: unknown;
}

/** Stubs `fetch` with one reply per `METHOD /path`; records every request. */
export function stubApi(replies: Record<string, () => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (request: Request) => {
    const url = new URL(request.url);
    const text = await request.text();
    calls.push({
      method: request.method,
      path: url.pathname,
      query: url.search.slice(1),
      authorization: request.headers.get("Authorization"),
      body: text === "" ? null : (JSON.parse(text) as unknown),
    });
    const reply = replies[`${request.method} ${url.pathname}`];
    if (reply === undefined) throw new Error(`unexpected ${request.method} ${url.pathname}`);
    return reply();
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
