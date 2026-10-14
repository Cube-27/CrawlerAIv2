import { problemOf, type Problem } from "./problem";

/** One server-sent event (WHATWG HTML §9.2): its type (`event`), its data, and the last event id the stream had set
 * when it was dispatched, which a reconnecting client sends back as `Last-Event-ID`. */
export interface StreamEvent {
  id: string | null;
  kind: string;
  data: string;
}

// WHATWG HTML §9.2.6: a line ends at CRLF, LF or CR.
const LINE_END = /\r\n|\r|\n/;

/** The `text/event-stream` interpretation of WHATWG HTML §9.2.6, fed text as it arrives. `retry` is not read: the
 * reconnect delay is the client's own backoff. */
export class EventStreamParser {
  private pending = "";
  private lastId: string | null;
  private kind = "";
  private data: string[] = [];

  /** `lastId` is the id a stream resumes after: it stays the events' id until the stream sets another. */
  constructor(lastId: string | null = null) {
    this.lastId = lastId;
  }

  /** The events `chunk` completes, in order. A CR at the end of a chunk is held, as it may start a CRLF. */
  push(chunk: string): StreamEvent[] {
    const text = this.pending + chunk;
    const held = text.endsWith("\r") ? 1 : 0;
    const lines = text.slice(0, text.length - held).split(LINE_END);
    this.pending = (lines.pop() ?? "") + text.slice(text.length - held);
    return lines.flatMap((line) => this.line(line));
  }

  private line(line: string): StreamEvent[] {
    if (line === "") return this.dispatch();
    if (line.startsWith(":")) return [];
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const raw = colon === -1 ? "" : line.slice(colon + 1);
    this.field(field, raw.startsWith(" ") ? raw.slice(1) : raw);
    return [];
  }

  private field(field: string, value: string): void {
    if (field === "data") this.data.push(value);
    else if (field === "event") this.kind = value;
    else if (field === "id" && !value.includes("\0")) this.lastId = value;
  }

  private dispatch(): StreamEvent[] {
    const event = { id: this.lastId, kind: this.kind === "" ? "message" : this.kind, data: this.data };
    this.kind = "";
    this.data = [];
    return event.data.length === 0 ? [] : [{ ...event, data: event.data.join("\n") }];
  }
}

/** Where a followed stream is: opening, receiving, waiting to reconnect, closed after its last event, or refused. */
export type StreamState = "connecting" | "live" | "reconnecting" | "ended" | "failed";

export interface FollowOptions {
  /** Opens one connection, resuming after `lastEventId` (from the start when null). */
  open: (lastEventId: string | null, signal: AbortSignal) => Promise<Response>;
  /** Whether `event` is the stream's last: after it the stream is not reopened. */
  isEnd: (event: StreamEvent) => boolean;
  onEvent: (event: StreamEvent) => void;
  onState: (state: StreamState) => void;
  /** The problem a refused connection answered with; the stream is not reopened. */
  onProblem: (problem: Problem) => void;
  signal: AbortSignal;
  /** How long to wait before a reconnect, after `attempt` reconnects in a row that received no event. */
  delayMs: (attempt: number) => number;
}

/** What one connection came to: the stream's end event was read, it dropped (reconnect), or it was refused. */
type Connection = { kind: "ended" } | { kind: "dropped"; received: boolean } | { kind: "refused" };

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

// RFC 9110 §15.5: a 4xx other than 429 (RFC 6585 §4) will not succeed if repeated; anything else may.
function isRefusal(status: number): boolean {
  return status >= 400 && status < 500 && status !== 429;
}

async function refusal(response: Response): Promise<Problem> {
  const body: unknown = await response.json().catch(() => null);
  return (
    problemOf(response, body) ?? {
      title: `The event stream was refused (HTTP ${String(response.status)}).`,
      detail: null,
      errors: [],
      retryAfter: null,
    }
  );
}

/** Reads one connection's events until it closes, the end event arrives, or the stream is stopped. */
async function readEvents(
  body: ReadableStream<Uint8Array>,
  parser: EventStreamParser,
  options: FollowOptions,
): Promise<Connection> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let received = false;
  for (;;) {
    const { done, value } = await reader.read();
    if (done || options.signal.aborted) return { kind: "dropped", received };
    for (const event of parser.push(decoder.decode(value, { stream: true }))) {
      received = true;
      options.onEvent(event);
      if (options.isEnd(event)) {
        await reader.cancel();
        return { kind: "ended" };
      }
    }
  }
}

async function connect(
  parser: EventStreamParser,
  lastEventId: string | null,
  options: FollowOptions,
): Promise<Connection> {
  let response: Response;
  try {
    response = await options.open(lastEventId, options.signal);
  } catch {
    // A network failure, or the stop: either way this connection is over.
    return { kind: "dropped", received: false };
  }
  if (isRefusal(response.status)) {
    options.onProblem(await refusal(response));
    return { kind: "refused" };
  }
  if (!response.ok || response.body === null) return { kind: "dropped", received: false };
  options.onState("live");
  try {
    return await readEvents(response.body, parser, options);
  } catch {
    return { kind: "dropped", received: true };
  }
}

/** Follows an SSE stream until its end event, reconnecting after a drop with the last id received as `Last-Event-ID`
 * (WHATWG HTML §9.2.4) and a growing delay, until `signal` stops it. Resolves when it stops. */
export async function followEvents(options: FollowOptions): Promise<void> {
  let lastId: string | null = null;
  let failures = 0;
  const onEvent = (event: StreamEvent) => {
    lastId = event.id;
    options.onEvent(event);
  };
  options.onState("connecting");
  while (!options.signal.aborted) {
    // A parser per connection, so a line a drop cut off is not joined to the next connection's first; it starts from
    // the last id, which outlives a reconnect (WHATWG HTML §9.2.6).
    const parser = new EventStreamParser(lastId);
    const connection = await connect(parser, lastId, { ...options, onEvent });
    if (options.signal.aborted) return;
    if (connection.kind !== "dropped") {
      options.onState(connection.kind === "ended" ? "ended" : "failed");
      return;
    }
    if (connection.received) failures = 0;
    options.onState("reconnecting");
    await wait(options.delayMs(failures), options.signal);
    failures += 1;
  }
}

/** The reconnect backoff: 1 s, doubling to at most 30 s. */
export function backoffMs(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, 30_000);
}
