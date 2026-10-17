/** Server-sent events (WHATWG HTML §9.2.5) as the job events endpoint sends them. */

/** One event: `kind` is the event name (`progress`, `completed`, ...), `id` the id to resume after, `data` the decoded
 * JSON payload (the raw text when it is not JSON). */
export interface JobEvent {
  kind: string;
  id: string | null;
  data: unknown;
}

/** The events of a response body, as they arrive; a comment (the server's keep-alive) is skipped. */
export async function* parseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<JobEvent> {
  const decoder = new TextDecoder();
  let pending = "";
  let kind = "";
  let id: string | null = null;
  let data: string[] = [];
  const reader = body.getReader();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      const lines = pending.split(/\r\n|\n|\r/);
      pending = done ? "" : (lines.pop() ?? "");
      for (const line of done ? [...lines, ""] : lines) {
        if (line === "") {
          if (data.length > 0) yield decode(kind, id, data.join("\n"));
          kind = "";
          data = [];
        } else if (!line.startsWith(":")) {
          const colon = line.indexOf(":");
          const name = colon < 0 ? line : line.slice(0, colon);
          const text = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
          if (name === "event") kind = text;
          else if (name === "id") id = text;
          else if (name === "data") data.push(text);
        }
      }
      if (done) return;
    }
  } finally {
    reader.releaseLock();
  }
}

function decode(kind: string, id: string | null, text: string): JobEvent {
  let data: unknown = text;
  try {
    data = JSON.parse(text);
  } catch {
    // Not JSON: the text stays as it came.
  }
  return { kind: kind === "" ? "message" : kind, id, data };
}
