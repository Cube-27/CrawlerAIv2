import { Card, Typography } from "@heroui/react";
import { useJobEvents } from "../../../api/hooks/events";
import { useJob, useJobRequest } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import { cancelState, type JobKind, type JobSummary } from "../../../api/jobs";
import { ActivityFeed } from "../../../components/ActivityFeed";
import { CancelJobAction } from "../../../components/CancelJobAction";
import { JobStatusLabel } from "../../../components/JobStatusLabel";
import { RunProgress } from "../../../components/RunProgress";
import { StatusLabel } from "../../../components/StatusLabel";
import type { Problem } from "../../../api/problem";
import { OutputArea, type OutputState } from "../OutputArea";
import { RecentRuns } from "./RecentRuns";
import { ResultsTable } from "./ResultsTable";
import { RunExports } from "./RunExports";
import { pageOutputs } from "./storedRequest";

/** A run's summary (SPEC-14 §4.3, D-0975), one outlined surface: its status with Cancel and the exports on the right,
 * kept in place as the run goes, then its progress and outcomes. */
function RunSummary({
  job,
  withMetadata,
  outputs,
}: Readonly<{ job: JobSummary; withMetadata: boolean; outputs: boolean }>) {
  const cancel = cancelState(job);
  return (
    <Card>
      <Card.Content className="flex flex-col gap-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <Typography.Heading level={2}>Run</Typography.Heading>
            <JobStatusLabel status={job.status} />
            {cancel === "requested" ? <StatusLabel text="cancel requested" tone="warning" /> : null}
          </div>
          <div className="flex flex-wrap items-start gap-2">
            {/* A cancel asked for ends the job once its claimed tasks end (SPEC-10 §4.2). */}
            <CancelJobAction id={job.id} isDisabled={cancel !== "cancellable"} />
            <RunExports jobId={job.id} withMetadata={withMetadata} outputs={outputs} />
          </div>
        </div>
        <RunProgress job={job} />
      </Card.Content>
    </Card>
  );
}

/** A job's run on the page (SPEC-14 §4.3, §4.5): one flow down the page, its summary, then its results table, then
 * its live activity, collapsed. The run's events feed the activity and read the summary and the table again. */
function JobRunView({ job, withMetadata }: Readonly<{ job: JobSummary; withMetadata: boolean }>) {
  const activity = useJobEvents(job.id);
  // A job without a schema has page outputs, not records (SPEC-10 §4.2): its request says which.
  const request = useJobRequest(job.id).data;
  const outputs = request !== undefined && pageOutputs(request);
  return (
    <>
      <RunSummary job={job} withMetadata={withMetadata} outputs={outputs} />
      {/* A crawl's pages open as a batch (SPEC-14 §2.8); a batch's or extract's are its own input. */}
      <ResultsTable
        jobId={job.id}
        withMetadata={withMetadata}
        selectable={job.kind === "crawl"}
        outputs={outputs}
      />
      <ActivityFeed activity={activity} />
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

/** The output of a mode that starts a job (Batch, Crawl, Extract): the start on its way (`starting`, its loading
 * label) or refused (`problem`), the run of `jobId`, or, before any run, the recent runs of `kind`. */
export function JobModeOutput({
  kind,
  starting,
  problem,
  jobId,
  withMetadata,
}: Readonly<{
  kind: JobKind;
  starting: string | null;
  problem: Problem | null;
  jobId: string | null;
  withMetadata: boolean;
}>) {
  if (starting !== null) return <OutputArea state={{ kind: "pending", label: starting }} />;
  if (problem !== null) return <OutputArea state={{ kind: "failed", problem }} />;
  if (jobId === null) return <RecentRuns kind={kind} />;
  return <JobRunOutput key={jobId} jobId={jobId} withMetadata={withMetadata} />;
}
