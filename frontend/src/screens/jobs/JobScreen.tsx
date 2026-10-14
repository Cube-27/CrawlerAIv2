import { Button, Typography } from "@heroui/react";
import type { ReactNode } from "react";
import { useParams } from "react-router";
import { useCancelJob, useJob } from "../../api/hooks/jobs";
import { problemOf } from "../../api/hooks/query";
import type { JobKind, JobStatus, JobSummary } from "../../api/jobs";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EventLog } from "../../components/EventLog";
import { JobStatusLabel } from "../../components/JobStatusLabel";
import { LoadingView } from "../../components/LoadingView";
import { OutcomeCounts } from "../../components/OutcomeCounts";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { UsageSummary } from "../../components/UsageSummary";
import { ExportActions } from "./ExportActions";
import { JobResults } from "./JobResults";

const KIND_LABELS: Readonly<Record<JobKind, string>> = {
  scrape: "Scrape",
  batch_scrape: "Batch scrape",
  map: "Map",
  crawl: "Crawl",
  extract: "Extract",
  learn: "Learn",
};

// SPEC-10 §4.2: a completed or failed job can't be cancelled (409); a cancelled one is already.
const CANCELLABLE: ReadonlySet<JobStatus> = new Set<JobStatus>(["queued", "running"]);

function CancelAction({ id }: Readonly<{ id: string }>) {
  const cancel = useCancelJob(id);
  const problem = problemOf(cancel.error);
  return (
    <>
      <ConfirmDialog
        trigger={
          <Button variant="danger" isPending={cancel.isPending}>
            Cancel job
          </Button>
        }
        title="Cancel this job?"
        confirmLabel="Cancel job"
        onConfirm={() => {
          cancel.mutate();
        }}
      >
        Its queued pages are not fetched. Pages already fetched keep their results.
      </ConfirmDialog>
      {problem === null ? null : <ProblemAlert problem={problem} />}
    </>
  );
}

function Section({ title, children }: Readonly<{ title: string; children: ReactNode }>) {
  return (
    <section className="flex flex-col gap-3">
      <Typography.Heading level={2}>{title}</Typography.Heading>
      {children}
    </section>
  );
}

function JobTimes({ job }: Readonly<{ job: JobSummary }>) {
  return (
    <Typography.Paragraph size="sm" color="muted">
      Job <Typography.Code>{job.id}</Typography.Code> · created {job.created_at} · started{" "}
      {job.started_at ?? "—"} · finished {job.finished_at ?? "—"}
    </Typography.Paragraph>
  );
}

function JobView({ job }: Readonly<{ job: JobSummary }>) {
  return (
    <section className="flex flex-col gap-6">
      <PageHeader
        title={`${KIND_LABELS[job.kind]} job`}
        actions={CANCELLABLE.has(job.status) ? <CancelAction id={job.id} /> : undefined}
      >
        <JobStatusLabel status={job.status} />
      </PageHeader>
      <JobTimes job={job} />
      <Section title="Tasks">
        <OutcomeCounts counts={job.counts} outcomes={job.outcomes} />
      </Section>
      <Section title="Usage">
        <UsageSummary usage={job.usage} />
      </Section>
      <EventLog jobId={job.id} />
      <Section title="Results">
        <ExportActions jobId={job.id} />
        <JobResults jobId={job.id} />
      </Section>
    </section>
  );
}

/** One job (SPEC-12 §4.3): its status and counts, usage, live events, results with exports, and a cancel. */
export function JobScreen() {
  const { id = "" } = useParams();
  const job = useJob(id);
  const problem = problemOf(job.error);
  if (problem !== null) return <ProblemAlert problem={problem} />;
  if (!job.isSuccess) return <LoadingView label="Loading the job" />;
  return <JobView key={id} job={job.data} />;
}
