import type { MethodHint, PageKind } from "../api/scrape";

/** The choices the scrape and job requests share, with their labels. */

export const PAGE_KINDS: readonly (readonly [PageKind, string])[] = [
  ["detail", "Detail"],
  ["listing", "Listing"],
];

export const METHOD_HINTS: readonly (readonly [MethodHint, string])[] = [
  ["auto", "Auto"],
  ["http", "HTTP"],
  ["browser", "Browser"],
];
