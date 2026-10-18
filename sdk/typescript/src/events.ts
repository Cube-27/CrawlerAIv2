/** Server-sent events (WHATWG HTML §9.2.5) as the job events endpoint sends them. */

/** One event: `kind` is the event name (`progress`, `completed`, ...), `id` the id to resume after, `data` the decoded
 * JSON payload (the raw text when it is not JSON). */
export interface JobEvent {
  kind: string;
  id: string | null;
  data: unknown;
}

/** Feeds lines, returns an event at each blank line; a comment (the server's keep-alive) is skipped. */
class LineParser {
  #kind = "";
  #id: string | null = null;
  #data: string[] = [];

  feed(line: string): JobEvent | null {
    if (line === "") return this.#dispatch();
    if (line.startsWith(":")) return null;
    const colon = line.indexOf(":");
    const name = colon < 0 ? line : line.slice(0, colon);
    const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (name === "event") this.#kind = value;
    else if (name === "id") this.#id = value;
    else if (name === "data") this.#data.push(value);
    return null;
  }

  #dispatch(): JobEvent | null {
    const lines = this.#data;
    const kind = this.#kind;
    this.#kind = "";
    this.#data = [];
    if (lines.length === 0) return null;
    return { kind: kind === "" ? "message" : kind, id: this.#id, data: decode(lines.join("\n")) };
  }
}

function decode(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text; // not JSON: the text stays as it came
  }
}

/** The lines of a byte stream, as they complete (WHATWG HTML §9.2.5: LF, CR or CRLF end one); the last, unfinished
 * line is returned when the stream ends. */
async function* lines(body: ReadableStream<Uint8Array>): AsyncGenerator<string> {
  const decoder = new TextDecoder();
  const reader = body.getReader();
  let pending = "";
  let ended = false;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      // A CR that ends a chunk may be the first half of a CRLF: it is kept until the next chunk shows which.
      const held = !done && pending.endsWith("\r") ? "\r" : "";
      const parts = pending.slice(0, pending.length - held.length).split(/\r\n|\n|\r/);
      pending = (parts.pop() ?? "") + held;
      yield* parts;
      if (done) break;
    }
    ended = true;
    if (pending !== "") yield pending;
  } finally {
    // A consumer that stops early (a `break` in `for await`) gets here before the stream ends: cancel the body so the
    // connection closes now rather than when the server ends it (WHATWG Streams: ReadableStreamDefaultReader.cancel).
    if (!ended) await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

/** The events of a response body, as they arrive. */
export async function* parseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<JobEvent> {
  const parser = new LineParser();
  for await (const line of lines(body)) {
    const event = parser.feed(line);
    if (event !== null) yield event;
  }
  const last = parser.feed("");
  if (last !== null) yield last;
}
