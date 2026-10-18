import type { JobKind } from "../../api/jobs";
import type { NewSchedule, Schedule, ScheduleChange, ScheduleKind } from "../../api/schedules";
import type { ModeId } from "../playground/modes";

/** The schedule kind of each mode a schedule can run (D-1418): a scrape runs as the batch of its URL on the server;
 * Map has no queued job to repeat. */
export const SCHEDULE_KINDS: Readonly<Partial<Record<ModeId, ScheduleKind>>> = {
  scrape: "scrape",
  batch: "batch_scrape",
  crawl: "crawl",
  extract: "extract",
};

/** The Schedule this dialog's fields: an interval in minutes (NaN while empty) or a 5-field cron expression. */
export interface ScheduleDraft {
  name: string;
  every: "interval" | "cron";
  minutes: number;
  cron: string;
  timezone: string;
}

/** The server's least interval (`core/cadence.py`): a minute, cron's own resolution. */
export const MIN_MINUTES = 1;

/** Why `draft` can't be sent, by request member. */
export function draftErrors(draft: ScheduleDraft): Readonly<Record<string, string>> {
  const errors: Record<string, string> = {};
  if (draft.name.trim() === "") errors["name"] = "Name the schedule.";
  if (draft.every === "interval" && !(draft.minutes >= MIN_MINUTES))
    errors["interval_s"] = "Run it every minute at most.";
  if (draft.every === "cron" && draft.cron.trim().split(/\s+/).length !== 5)
    errors["cron"] =
      "A cron expression has 5 fields: minute, hour, day of month, month, day of week.";
  if (draft.timezone.trim() === "") errors["timezone"] = "Name an IANA time zone, such as UTC.";
  return errors;
}

/** The `POST /v1/schedules` body for `request` (what `kind`'s action would send) on `draft`'s cadence. */
export function scheduleBody(
  kind: ScheduleKind,
  request: object,
  draft: ScheduleDraft,
): NewSchedule {
  const cadence =
    draft.every === "interval"
      ? { interval_s: Math.round(draft.minutes * 60) }
      : { cron: draft.cron.trim().replace(/\s+/g, " ") };
  return { name: draft.name.trim(), kind, request, timezone: draft.timezone.trim(), ...cadence };
}

/** How often a schedule runs, in words: "Every 15 min", "Every 2 h", or its cron expression and zone. */
export function cadenceText({
  cron,
  interval_s,
  timezone,
}: Pick<Schedule, "cron" | "interval_s" | "timezone">): string {
  if (cron !== null) return `Cron ${cron} (${timezone})`;
  const seconds = interval_s ?? 0;
  if (seconds % 3600 === 0) return `Every ${String(seconds / 3600)} h`;
  if (seconds % 60 === 0) return `Every ${String(seconds / 60)} min`;
  return `Every ${String(seconds)} s`;
}

/** The schedule kind a stored run of each job kind is repeated as (D-1514); `map` and `learn` have none. */
export const RUN_SCHEDULE_KINDS: Readonly<Partial<Record<JobKind, ScheduleKind>>> = {
  scrape: "scrape",
  batch_scrape: "batch_scrape",
  crawl: "crawl",
  extract: "extract",
};

/** The schedule draft that shows `schedule` as it is, for the Edit dialog; its `minutes` are those of its interval. */
export function draftOf(schedule: Schedule): ScheduleDraft {
  const seconds = schedule.interval_s ?? 0;
  return {
    name: schedule.name,
    every: schedule.cron === null ? "interval" : "cron",
    minutes: seconds > 0 ? seconds / 60 : 60,
    cron: schedule.cron ?? "",
    timezone: schedule.timezone,
  };
}

/** What `PATCH /v1/schedules/{id}` is sent for an edit of `schedule` to `draft` and `request` (the request's JSON text,
 * `initial` the text it was shown as): only the members that changed, so an unchanged request is not checked again and
 * an interval that is not whole minutes is not rounded. A request that is not a JSON object is `null`. */
export function scheduleChange(
  schedule: Schedule,
  draft: ScheduleDraft,
  request: { text: string; initial: string },
): ScheduleChange | null {
  const before = draftOf(schedule);
  const change: ScheduleChange = {};
  if (draft.name.trim() !== schedule.name) change.name = draft.name.trim();
  const cadence = scheduleBody(schedule.kind, {}, draft);
  const cadenceChanged =
    draft.every !== before.every ||
    draft.timezone.trim() !== schedule.timezone ||
    (draft.every === "interval"
      ? draft.minutes !== before.minutes
      : draft.cron.trim().replace(/\s+/g, " ") !== schedule.cron);
  if (cadenceChanged) {
    Object.assign(change, {
      timezone: cadence.timezone,
      ...(cadence.cron === undefined ? { interval_s: cadence.interval_s } : { cron: cadence.cron }),
    });
  }
  if (request.text !== request.initial) {
    const parsed = parseRequest(request.text);
    if (parsed === null) return null;
    Object.assign(change, { kind: schedule.kind, request: parsed });
  }
  return change;
}

/** The request as a JSON object, or null when the text is not one. */
export function parseRequest(text: string): object | null {
  try {
    const value: unknown = JSON.parse(text);
    return typeof value === "object" && value !== null && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}
