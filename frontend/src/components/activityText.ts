import type { StreamEvent } from "../api/events";
import { isJsonObject, type JsonObject } from "../api/json";

/** Each run event (SPEC-10 §4.2) as one plain-language line (SPEC-14 §4.5), the one place that wording lives. A line
 * says only what the event's data says: an event whose data lacks a member its line needs, or of a kind not listed
 * here, is shown as its kind name, never dropped. */

function text(data: JsonObject, name: string): string | null {
  const value = data[name];
  return typeof value === "string" ? value : null;
}

function count(data: JsonObject, name: string): number | null {
  const value = data[name];
  return typeof value === "number" ? value : null;
}

function plural(n: number, word: string): string {
  return `${String(n)} ${word}${n === 1 ? "" : "s"}`;
}

// FetchSummary.method (SPEC-02): how the page was fetched.
const METHODS: Readonly<Record<string, string>> = {
  http: "Fetched over HTTP.",
  browser: "Fetched with a browser.",
};

// SPEC-02 §4.4: the block class of a page that came back as itself.
const NOT_BLOCKED = "ok";

function fetched(data: JsonObject): string | null {
  const method = text(data, "method");
  const blockClass = text(data, "block_class");
  if (method === null) return null;
  const how = METHODS[method] ?? `Fetched (${method}).`;
  return blockClass === null || blockClass === NOT_BLOCKED
    ? how
    : `${how} Block class: ${blockClass}.`;
}

function extracted(data: JsonObject): string | null {
  const outcome = text(data, "outcome");
  const mode = text(data, "mode");
  const llmCalls = count(data, "llm_calls");
  if (outcome === null || mode === null) return null;
  const line = `Extracted: ${outcome} (${mode}).`;
  return llmCalls === null || llmCalls === 0
    ? line
    : `${line} Used ${plural(llmCalls, "LLM call")}.`;
}

function abstained(data: JsonObject): string | null {
  const fields = data["fields"];
  if (!Array.isArray(fields) || fields.length === 0) return null;
  return `Did not publish ${fields.map(String).join(", ")}.`;
}

function taskFailed(data: JsonObject): string | null {
  const attempts = count(data, "attempts");
  const error = text(data, "last_error");
  if (attempts === null) return null;
  const line = `Failed after ${plural(attempts, "attempt")}`;
  return error === null ? `${line}.` : `${line}: ${error}`;
}

function driftSuspended(data: JsonObject): string | null {
  const field = text(data, "field");
  return field === null ? null : `Paused ${field} in this site's config: its output changed.`;
}

function learningFinished(data: JsonObject): string | null {
  if (text(data, "config_id") !== null) return "Learned this site's config.";
  const reason = text(data, "reason");
  return reason === null ? null : `Learning ended without a config: ${reason}.`;
}

type Line = (data: JsonObject) => string | null;

const LINES: Readonly<Record<string, Line>> = {
  task_fetched: fetched,
  task_extracted: extracted,
  task_abstained: abstained,
  task_failed: taskFailed,
  drift_suspended: driftSuspended,
  learning_started: () => "Learning this site's config…",
  learning_finished: learningFinished,
  completed: () => "Run finished.",
  failed: () => "Run failed.",
  cancelled: () => "Run cancelled.",
};

// SPEC-10 §4.2: the task counts after each batch of events. They update the counts, and are no line of their own.
const PROGRESS = "progress";

function parsed(data: string): JsonObject {
  try {
    const value: unknown = JSON.parse(data);
    return isJsonObject(value) ? value : {};
  } catch {
    return {};
  }
}

/** The event's line; null for `progress`, which has none. */
export function activityLine(event: StreamEvent): string | null {
  if (event.kind === PROGRESS) return null;
  const line = LINES[event.kind];
  return (line === undefined ? null : line(parsed(event.data))) ?? event.kind;
}

/** The task URL an event is about, or null for an event about the whole run. */
export function eventUrl(event: StreamEvent): string | null {
  return text(parsed(event.data), "url");
}
