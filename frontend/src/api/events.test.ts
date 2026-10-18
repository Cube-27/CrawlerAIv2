import { describe, expect, it, vi } from "vite-plus/test";
import { createApiClient } from "./client";
import {
  EventStreamParser,
  followEvents,
  type Opened,
  type StreamEvent,
  type StreamState,
} from "./events";
import { openJobEvents } from "./jobs";

/** A connection answered with `body`. */
function answered(body: BodyInit, init?: ResponseInit): Opened {
  return { response: new Response(body, init) };
}

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

describe("EventStreamParser", () => {
  it("dispatches an event at each blank line with its id, type and data", () => {
    const parser = new EventStreamParser();

    const events = parser.push('id: 7\nevent: task_fetched\ndata: {"url":"a"}\n\n');

    expect(events).toEqual([{ id: "7", kind: "task_fetched", data: '{"url":"a"}' }]);
  });

  it("reads lines split across chunks and every line ending, and skips comments", () => {
    const parser = new EventStreamParser();

    const first = parser.push(": keep-alive\r\nid: 1\r");
    const second = parser.push("\ndata: x");
    const third = parser.push("\r\rdata: y\n\n");

    expect([first, second, third]).toEqual([
      [],
      [],
      [
        { id: "1", kind: "message", data: "x" },
        { id: "1", kind: "message", data: "y" },
      ],
    ]);
  });
});

interface Run {
  requests: (string | null)[];
  events: StreamEvent[];
  states: StreamState[];
  problem: string | null;
}

/** Follows a stream whose connections answer `responses` in turn, with no wait between them. */
async function follow(responses: (() => Opened)[], idleMs = 60_000): Promise<Run> {
  const run: Run = { requests: [], events: [], states: [], problem: null };
  await followEvents({
    open: (lastEventId) => {
      run.requests.push(lastEventId);
      const next = responses.shift();
      if (next === undefined) throw new Error("no more connections expected");
      return Promise.resolve(next());
    },
    isEnd: (event) => event.kind === "completed",
    onEvent: (event) => run.events.push(event),
    onState: (state) => run.states.push(state),
    onProblem: (problem) => {
      run.problem = problem.title;
    },
    signal: new AbortController().signal,
    delayMs: () => 0,
    idleMs,
  });
  return run;
}

describe("followEvents", () => {
  it("reconnects after a dropped stream with the last id received as Last-Event-ID", async () => {
    const run = await follow([
      () => answered(streamOf("id: 1\nevent: task_fetched\ndata: {}\n\nid: 2\ndata: {}\n\n")),
      () =>
        answered(streamOf("event: progress\ndata: {}\n\nid: 3\nevent: completed\ndata: {}\n\n")),
    ]);

    expect(run.requests).toEqual([null, "2"]);
    expect(run.events.map((event) => event.id)).toEqual(["1", "2", "2", "3"]);
    expect(run.states).toEqual(["connecting", "live", "reconnecting", "live", "ended"]);
  });

  it("reconnects after a server error or a rate limit whose body the client has read", async () => {
    // openapi-fetch reads a non-OK answer's body to parse it, so the stream it hands back is locked.
    const answers = [
      () => new Response("upstream down", { status: 502 }),
      () => Response.json({ status: 429, title: "Too many requests" }, { status: 429 }),
      () => new Response(streamOf("id: 9\nevent: completed\ndata: {}\n\n")),
    ];
    vi.stubGlobal("fetch", (request: Request) => {
      const next = answers.shift();
      if (next === undefined) throw new Error(`no more connections expected: ${request.url}`);
      return Promise.resolve(next());
    });
    const client = createApiClient({ baseUrl: "http://api.test" });
    const states: StreamState[] = [];

    await followEvents({
      open: (lastEventId, signal) => openJobEvents(client, "job-1", lastEventId, signal),
      isEnd: (event) => event.kind === "completed",
      onEvent: () => undefined,
      onState: (state) => states.push(state),
      onProblem: () => undefined,
      signal: new AbortController().signal,
      delayMs: () => 0,
      idleMs: 60_000,
    });

    expect(states).toEqual(["connecting", "reconnecting", "reconnecting", "live", "ended"]);
  });

  it("stops on a client error and reports its problem", async () => {
    const body = { status: 404, title: "Not found", detail: "no job" };
    const response = new Response(null, {
      status: 404,
      headers: { "content-type": "application/problem+json" },
    });
    const run = await follow([() => ({ response, error: body })]);

    expect(run.problem).toBe("Not found");
    expect(run.states).toEqual(["connecting", "failed"]);
  });
});
