import { Typography } from "@heroui/react";
import { useJobEvents } from "../../../api/hooks/events";
import { useJob } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import type { JobStatus, JobSummary } from "../../../api/jobs";
import { CancelJobAction } from "../../../components/CancelJobAction";
import { JobStatusLabel } from "../../../components/JobStatusLabel";
import { OutcomeCounts } from "../../../components/OutcomeCounts";
import { StatusLabel } from "../../../components/StatusLabel";
import { OutputArea, type OutputState } from "../OutputArea";
import { ElapsedTime } from "./ElapsedTime";
import { ResultsTable } from "./ResultsTable";
import { RunExports } from "./RunExports";

// SPEC-10 §4.2: a completed or failed job can't be cancelled (409); a cancelled one is already.
const CANCELLABLE: ReadonlySet<JobStatus> = new Set<JobStatus>(["queued", "running"]);

/** A run's status line: its status, elapsed time, Cancel and the exports, on one row that keeps its controls in place
 * as the run goes. */
function RunHeader({ job, withMetadata }: Readonly<{ job: JobSummary; withMetadata: boolean }>) {
  const cancellable = CANCELLABLE.has(job.status);
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Typography.Heading level={2}>Run</Typography.Heading>
        <JobStatusLabel status={job.status} />
        {cancellable && job.cancel_requested ? (
          <StatusLabel text="cancel requested" tone="warning" />
        ) : null}
        <ElapsedTime startedAt={job.started_at} finishedAt={job.finished_at} />
      </div>
      <div className="flex flex-wrap items-start gap-2">
        {/* A cancel asked for ends the job once its claimed tasks end (SPEC-10 §4.2). */}
        <CancelJobAction id={job.id} isDisabled={!cancellable || job.cancel_requested} />
        <RunExports jobId={job.id} withMetadata={withMetadata} />
      </div>
    </div>
  );
}

/** A job's run on the page (SPEC-14 §4.3): its status line, counts and results table, refreshed by its events. */
function JobRunView({ job, withMetadata }: Readonly<{ job: JobSummary; withMetadata: boolean }>) {
  // Follows the run's events while it shows: they read the summary and the results table again.
  useJobEvents(job.id);
  return (
    <>
      <RunHeader job={job} withMetadata={withMetadata} />
      <OutcomeCounts counts={job.counts} outcomes={job.outcomes} />
      <ResultsTable jobId={job.id} withMetadata={withMetadata} />
    </>
  );
}

/** The output area for the job `jobId`: loading, its problem, or its run. `withMetadata` (Metadata in JSON) asks the
 * results for each page's metadata. */
export function JobRunOutput({
  jobId,
  withMetadata,
}: Readonly<{ jobId: string; withMetadata: boolean }>) {
  const job = useJob(jobId);
  const problem = problemOf(job.error);
  let state: OutputState;
  if (problem !== null) state = { kind: "failed", problem };
  else if (job.isSuccess)
    state = { kind: "done", content: <JobRunView job={job.data} withMetadata={withMetadata} /> };
  else state = { kind: "pending", label: "Loading the run" };
  return <OutputArea state={state} />;
}
