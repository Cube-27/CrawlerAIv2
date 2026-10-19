import type { JobSummary } from "../api/jobs";

/** A running batch job's summary (jobs spec): three tasks, two done and extracted, one queued. */
export function jobSummary(overrides: Partial<JobSummary> & Pick<JobSummary, "id">): JobSummary {
  return {
    kind: "batch_scrape",
    status: "running",
    counts: { queued: 1, claimed: 0, done: 2, failed: 0, cancelled: 0 },
    outcomes: {
      extracted: 2,
      partial: 0,
      unchanged: 0,
      links_only: 0,
      blocked: 0,
      shell: 0,
      not_found: 0,
      no_match: 0,
      auth_wall: 0,
      soft_404: 0,
      geo_redirect: 0,
      redirected_to_listing: 0,
      unsupported_media: 0,
      geo_blocked: 0,
      timeout: 0,
      failed: 0,
    },
    usage: { pages_fetched: 2 },
    llm_cost_usd: 0.0123,
    created_at: "2026-10-14T09:00:00Z",
    started_at: "2026-10-14T09:00:01Z",
    finished_at: null,
    engine_version: "0.0.0",
    webhook_url: null,
    schedule_id: null,
    cancel_requested: false,
    start_url: null,
    url_count: 3,
    ...overrides,
  };
}
