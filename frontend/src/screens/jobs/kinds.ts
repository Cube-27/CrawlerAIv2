import type { JobKind } from "../../api/jobs";

/** Each `job.kind` (persistence-storage spec) as the job screens name it. */
export const KIND_LABELS: Readonly<Record<JobKind, string>> = {
  scrape: "Scrape",
  batch_scrape: "Batch scrape",
  map: "Map",
  crawl: "Crawl",
  extract: "Extract",
  learn: "Learn",
};
