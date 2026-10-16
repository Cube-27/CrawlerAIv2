import { Button, Disclosure, Typography } from "@heroui/react";
import { useMemo } from "react";
import type { JobEvents } from "../api/hooks/events";
import { activityEntry } from "./activityText";
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

/** A run's live activity (SPEC-14 §4.5, D-0975): its events as plain-language lines grouped by task URL, the newest
 * group first, in a fixed-height box that scrolls. It is collapsed under the results: the run's progress is in its
 * header, so the lines are detail a reader opens when they want it. */
export function ActivityFeed({ activity }: Readonly<{ activity: JobEvents }>) {
  // Only a new event changes the lines; the summary above re-renders the feed on every progress event.
  const groups = useMemo(() => activityGroups(activity.events), [activity.events]);
  return (
    <Disclosure>
      <div className="flex flex-wrap items-center gap-3">
        <Disclosure.Heading>
          <Button slot="trigger" variant="ghost" size="sm">
            Activity
            <Disclosure.Indicator />
          </Button>
        </Disclosure.Heading>
        <StreamStateLabel state={activity.state} />
      </div>
      <Disclosure.Content>
        <Disclosure.Body className="flex flex-col gap-3 pt-3">
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
        </Disclosure.Body>
      </Disclosure.Content>
    </Disclosure>
  );
}
