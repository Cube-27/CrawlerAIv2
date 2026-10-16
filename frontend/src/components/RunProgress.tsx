import { ProgressBar, Typography } from "@heroui/react";
import type { JobSummary } from "../api/jobs";
import { plural } from "./activityText";
import { DurationText } from "./Duration";
import { endedTasks, OutcomeSummary, taskTotal } from "./OutcomeCounts";

/** A run's progress (SPEC-14 §4.3, D-0975): a bar of the pages done, "N of M pages done" and the elapsed time under
 * it, and the outcomes reached so far on the right. */
export function RunProgress({ job }: Readonly<{ job: JobSummary }>) {
  const ended = endedTasks(job.counts);
  const total = taskTotal(job.counts);
  return (
    <div className="flex flex-col gap-3">
      <ProgressBar aria-label="Pages done" size="sm" value={ended} maxValue={Math.max(total, 1)}>
        <ProgressBar.Track>
          <ProgressBar.Fill />
        </ProgressBar.Track>
      </ProgressBar>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-x-3">
          <Typography.Paragraph size="sm" weight="medium">
            {`${String(ended)} of ${plural(total, "page")} done`}
          </Typography.Paragraph>
          <Typography.Paragraph size="sm" color="muted">
            Elapsed <DurationText startedAt={job.started_at} finishedAt={job.finished_at} />
          </Typography.Paragraph>
        </div>
        <OutcomeSummary outcomes={job.outcomes} />
      </div>
    </div>
  );
}
