import type { TaskOutcome } from "../api/jobs";
import { StatusLabel, type StatusTone } from "./StatusLabel";

// One tone per `url_task.outcome`. `partial` and `shell` returned a page without all it should have;
// `blocked`, `timeout` and `failed` returned none. `not_found` is the page's own answer; `unchanged` (a record still current),
// `links_only` (a page read for its links) and `no_match` (a discovered page without its required fields, §10) are
// not failures. `auth_wall` (a 401), `soft_404`, `geo_redirect` and `redirected_to_listing` (where a redirect led
// instead of the page) are the site's answers, as `not_found` is.
const OUTCOME_TONES: Record<TaskOutcome, StatusTone> = {
  extracted: "success",
  unchanged: "success",
  partial: "warning",
  shell: "warning",
  not_found: "neutral",
  links_only: "neutral",
  no_match: "neutral",
  auth_wall: "neutral",
  soft_404: "neutral",
  geo_redirect: "neutral",
  redirected_to_listing: "neutral",
  blocked: "danger",
  timeout: "danger",
  failed: "danger",
};

/** A URL's outcome as its text and icon. */
export function OutcomeLabel({ outcome }: Readonly<{ outcome: TaskOutcome }>) {
  return <StatusLabel text={outcome} tone={OUTCOME_TONES[outcome]} />;
}
