import type { JsonValuesItem } from "../../../api/jobs";
import type { ScrapeRecord, ScrapeResponse } from "../../../api/scrape";

/** Code-unit order of two strings, the order Python's `sorted` gives the server. */
function codeUnitOrder(a: string, b: string): number {
  if (a < b) return -1;
  return a > b ? 1 : 0;
}

/** A clean record (SPEC-14 §4.4): each field's published value, or null, picked from the record the server sent. A
 * field's `value` is its published value or null (SPEC-07 §4.4), so nothing is decided here. Names are in name order
 * (D-0816), as `json_values` has them; schema names are ASCII (`NAME_PATTERN`), so code-unit order is that order. */
function cleanRecord(record: ScrapeRecord): JsonValuesItem["records"][number] {
  return Object.fromEntries(
    Object.keys(record.fields)
      .sort(codeUnitOrder)
      .map((name) => [name, record.fields[name]?.value ?? null]),
  );
}

/** One scrape as the item `json_values` gives a job's page (SPEC-14 §4.4 Single scrape): its URL, outcome, clean
 * records and, with `withMetadata`, the page's metadata when the response carries it. */
export function scrapeItem(response: ScrapeResponse, withMetadata: boolean): JsonValuesItem {
  return {
    url: response.url,
    outcome: response.outcome,
    records: (response.records ?? []).map(cleanRecord),
    ...(withMetadata && response.metadata !== undefined ? { metadata: response.metadata } : {}),
  };
}

/** Whether a published field of `records` is uncalibrated (DESIGN.md, Showing extraction results). */
export function hasUncalibrated(records: readonly ScrapeRecord[]): boolean {
  return records.some((record) =>
    Object.values(record.fields).some((field) => field.status === "published" && !field.calibrated),
  );
}
