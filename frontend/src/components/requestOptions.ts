import type { MethodHint, PageKind } from "../api/scrape";

/** The choices the scrape and job requests share, with their labels. */

export const PAGE_KIND_LABELS: Readonly<Record<PageKind, string>> = {
  detail: "Detail",
  listing: "Listing",
};

export const PAGE_KINDS: readonly (readonly [PageKind, string])[] = [
  ["detail", PAGE_KIND_LABELS.detail],
  ["listing", PAGE_KIND_LABELS.listing],
];

export const METHOD_HINTS: readonly (readonly [MethodHint, string])[] = [
  ["auto", "Auto"],
  ["http", "HTTP"],
  ["browser", "Browser"],
];
