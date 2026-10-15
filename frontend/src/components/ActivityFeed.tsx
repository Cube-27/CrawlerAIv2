import { Typography } from "@heroui/react";
import { useId, useMemo } from "react";
import type { JobEvents } from "../api/hooks/events";
import type { JobSummary } from "../api/jobs";
import { activityEntry } from "./activityText";
import { ElapsedTime } from "./ElapsedTime";
import { ProblemAlert } from "./ProblemAlert";
import { StreamStateLabel } from "./StreamStateLabel";

/** One line, keyed by its event's place in the stream: events only ever arrive after it. */
interface Line {
  key: number;
  text: string;
}

/** The lines about one task URL, or about the whole run (`url` null). */
interface Group {
  url: string | null;
  lines: Line[];
}

/** The events' lines grouped by task URL, the group with the latest event first; lines keep their order. */
export function activityGroups(events: JobEvents["events"]): Group[] {
  const groups = new Map<string | null, Group>();
  events.forEach((event, key) => {
    const entry = activityEntry(event);
    if (entry === null) return;
    const { text, url } = entry;
    const group = groups.get(url) ?? { url, lines: [] };
    group.lines.push({ key, text });
    // Moved to the end of the map's order, which is newest last.
    groups.delete(url);
    groups.set(url, group);
  });
  return [...groups.values()].reverse();
}

/** How many of the job's tasks have ended, of all of them. */
function progressText({ counts }: JobSummary): string {
  const ended = counts.done + counts.failed + counts.cancelled;
  const total = ended + counts.queued + counts.claimed;
  return `${String(ended)} of ${String(total)} pages done`;
}

/** A run's live activity (SPEC-14 §4.5): its events as plain-language lines grouped by task URL, the newest group
 * first, under its progress and elapsed time, in a fixed-height box that scrolls. */
export function ActivityFeed({
  job,
  activity,
}: Readonly<{ job: JobSummary; activity: JobEvents }>) {
  const headingId = useId();
  // Only a new event changes the lines; the summary above re-renders the feed on every progress event.
  const groups = useMemo(() => activityGroups(activity.events), [activity.events]);
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Typography.Heading level={2} id={headingId}>
          Activity
        </Typography.Heading>
        <StreamStateLabel state={activity.state} />
      </div>
      <div className="flex flex-wrap gap-x-3">
        <Typography.Paragraph size="sm">{progressText(job)}</Typography.Paragraph>
        <ElapsedTime startedAt={job.started_at} finishedAt={job.finished_at} />
      </div>
      {activity.problem === null ? null : <ProblemAlert problem={activity.problem} />}
      <ol aria-label="Activity" className="flex h-activity-feed flex-col gap-3 overflow-y-auto">
        {groups.length === 0 ? (
          <li>
            <Typography.Paragraph size="sm" color="muted">
              No activity yet.
            </Typography.Paragraph>
          </li>
        ) : null}
        {groups.map((group) => (
          <li key={group.url ?? ""} className="flex flex-col gap-1">
            <Typography.Paragraph size="sm" weight="medium" className="truncate">
              {group.url ?? "This run"}
            </Typography.Paragraph>
            <ul aria-label={group.url ?? "This run"} className="flex flex-col gap-0.5">
              {group.lines.map((line) => (
                <li key={line.key}>
                  <Typography.Paragraph size="sm" color="muted">
                    {line.text}
                  </Typography.Paragraph>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </section>
  );
}
