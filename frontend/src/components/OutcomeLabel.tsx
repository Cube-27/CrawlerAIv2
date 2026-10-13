import type { ScrapeOutcome } from "../api/scrape";
import { StatusLabel, type StatusTone } from "./StatusLabel";

// One tone per `url_task.outcome` (ARCHITECTURE §6). `partial` and `shell` returned a page without all it should have;
// `blocked` and `failed` returned none. `not_found` is the page's own answer.
const OUTCOME_TONES: Record<ScrapeOutcome, StatusTone> = {
  extracted: "success",
  partial: "warning",
  shell: "warning",
  not_found: "neutral",
  blocked: "danger",
  failed: "danger",
};

/** A URL's outcome as its text and icon. */
export function OutcomeLabel({ outcome }: Readonly<{ outcome: ScrapeOutcome }>) {
  return <StatusLabel text={outcome} tone={OUTCOME_TONES[outcome]} />;
}
