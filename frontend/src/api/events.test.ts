import { describe, expect, it } from "vite-plus/test";
import {
  EventStreamParser,
  followEvents,
  type Opened,
  type StreamEvent,
  type StreamState,
} from "./events";

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

  it("joins data lines with a line feed and types an event without `event` as `message`", () => {
    const parser = new EventStreamParser();

    expect(parser.push("data: one\ndata:two\n\n")).toEqual([
      { id: null, kind: "message", data: "one\ntwo" },
    ]);
  });

  it("keeps the last id for an event that sends none, as WHATWG HTML §9.2.6 does", () => {
    const parser = new EventStreamParser();

    const events = parser.push("id: 3\ndata: a\n\nevent: progress\ndata: b\n\n");

    expect(events.map((event) => event.id)).toEqual(["3", "3"]);
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

  it("dispatches nothing for an event without data", () => {
    const parser = new EventStreamParser();

    expect(parser.push("id: 4\nevent: progress\n\n")).toEqual([]);
  });
});

interface Run {
  requests: (string | null)[];
  events: StreamEvent[];
  states: StreamState[];
  problem: string | null;
}

/** Follows a stream whose connections answer `responses` in turn, with no wait between them. */
async function follow(responses: (() => Opened)[]): Promise<Run> {
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

  it("reconnects after a server error and a network failure", async () => {
    const run = await follow([
      () => answered("down", { status: 503 }),
      () => {
        throw new TypeError("network");
      },
      () => answered(streamOf("id: 9\nevent: completed\ndata: {}\n\n")),
    ]);

    expect(run.requests).toEqual([null, null, null]);
    expect(run.states).toEqual(["connecting", "reconnecting", "reconnecting", "live", "ended"]);
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
