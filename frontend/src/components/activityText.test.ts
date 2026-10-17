import { describe, expect, it } from "vite-plus/test";
import type { StreamEvent } from "../api/events";
import { activityGroups } from "./ActivityFeed";
import { activityEntry } from "./activityText";

const URL_A = "https://shop.test/items/1";

function event(kind: string, data: object, id: string | null = "1"): StreamEvent {
  return { id, kind, data: JSON.stringify(data) };
}

// Every event kind SPEC-10 §4.2 lists, with the data the worker records for it.
const LINES: readonly [string, object, string | null][] = [
  ["task_fetched", { url: URL_A, method: "http", block_class: "ok" }, "Fetched over HTTP."],
  ["task_fetched", { url: URL_A, method: "browser", block_class: "ok" }, "Fetched with a browser."],
  [
    "task_fetched",
    { url: URL_A, method: "http", block_class: "captcha" },
    "Fetched over HTTP. Block class: captcha.",
  ],
  [
    "task_extracted",
    { url: URL_A, outcome: "extracted", mode: "config", llm_calls: 0 },
    "Extracted: extracted (config).",
  ],
  [
    "task_extracted",
    { url: URL_A, outcome: "partial", mode: "adhoc", llm_calls: 2 },
    "Extracted: partial (adhoc). Used 2 LLM calls.",
  ],
  ["task_abstained", { url: URL_A, fields: ["brand", "price"] }, "Did not publish brand, price."],
  [
    "task_failed",
    { task_id: "t1", url: URL_A, attempts: 3, last_error: "timeout after 30 s" },
    "Failed after 3 attempts: timeout after 30 s",
  ],
  [
    "task_failed",
    { task_id: "t1", url: URL_A, attempts: 1, last_error: null },
    "Failed after 1 attempt.",
  ],
  [
    "drift_suspended",
    { config_id: "c1", field: "price", pages: 20, yield: 0.1, validity: 0.5 },
    "Paused price in this site's config: its output changed.",
  ],
  [
    "absent_stated",
    { config_id: "c1", field: "sku" },
    "Found sku, which this site's config listed as absent: relearning.",
  ],
  ["learning_started", {}, "Learning this site's config…"],
  [
    "learning_finished",
    { config_id: "c1", reason: "pending_approval", report: null },
    "Learned this site's config; it waits for approval.",
  ],
  [
    "learning_finished",
    { config_id: "c1", reason: "learned", report: null },
    "Learned this site's config.",
  ],
  [
    "learning_finished",
    { config_id: null, reason: "no_candidates", report: null },
    "Learning ended without a config: no_candidates.",
  ],
  ["progress", { counts: {}, outcomes: {} }, null],
  ["completed", {}, "Run finished."],
  ["failed", {}, "Run failed."],
  ["cancelled", {}, "Run cancelled."],
];

/** The event's line; null when it has none. */
function activityLine(e: StreamEvent): string | null {
  return activityEntry(e)?.text ?? null;
}

describe("activityEntry", () => {
  it.each(LINES)("words %s %j as %j", (kind, data, line) => {
    expect(activityLine(event(kind, data))).toBe(line);
  });

  it("shows an unknown kind as its name", () => {
    expect(activityLine(event("task_retried", { url: URL_A }))).toBe("task_retried");
  });

  it("shows a known kind as its name when its data lacks what the line would say", () => {
    expect(activityLine(event("task_extracted", { url: URL_A }))).toBe("task_extracted");
    expect(activityLine({ id: "1", kind: "task_failed", data: "not json" })).toBe("task_failed");
  });
});

describe("activityEntry's url", () => {
  it("is the task URL the event carries, or null for the whole run", () => {
    expect(activityEntry(event("task_fetched", { url: URL_A, method: "http" }))?.url).toBe(URL_A);
    expect(activityEntry(event("completed", {}))?.url).toBeNull();
  });
});

describe("activityGroups", () => {
  it("groups lines by task URL, the group with the latest event first, lines in order, without progress", () => {
    const urlB = "https://shop.test/items/2";
    const groups = activityGroups([
      event("task_fetched", { url: URL_A, method: "http", block_class: "ok" }, "1"),
      event("task_fetched", { url: urlB, method: "browser", block_class: "ok" }, "2"),
      event(
        "task_extracted",
        { url: URL_A, outcome: "extracted", mode: "config", llm_calls: 0 },
        "3",
      ),
      event("progress", {}, null),
      event("completed", {}, "4"),
    ]);

    expect(groups.map(({ url, lines }) => [url, lines.map(({ text }) => text)])).toEqual([
      [null, ["Run finished."]],
      [URL_A, ["Fetched over HTTP.", "Extracted: extracted (config)."]],
      [urlB, ["Fetched with a browser."]],
    ]);
  });
});
