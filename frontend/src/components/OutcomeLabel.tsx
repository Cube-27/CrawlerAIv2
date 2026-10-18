import type { TaskOutcome } from "../api/jobs";
import { StatusLabel, type StatusTone } from "./StatusLabel";

// One tone per `url_task.outcome`. `partial` and `shell` returned a page without all it should have;
// `blocked` and `failed` returned none. `not_found` is the page's own answer; `unchanged` (a record still current),
// `links_only` (a page read for its links) and `no_match` (a discovered page without its required fields, §10) are
// not failures.
const OUTCOME_TONES: Record<TaskOutcome, StatusTone> = {
  extracted: "success",
  unchanged: "success",
  partial: "warning",
  shell: "warning",
  not_found: "neutral",
  links_only: "neutral",
  no_match: "neutral",
  blocked: "danger",
  failed: "danger",
};

/** A URL's outcome as its text and icon. */
export function OutcomeLabel({ outcome }: Readonly<{ outcome: TaskOutcome }>) {
  return <StatusLabel text={outcome} tone={OUTCOME_TONES[outcome]} />;
}
