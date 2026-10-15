import { Typography } from "@heroui/react";
import { useParams } from "react-router";
import { useJob } from "../../api/hooks/jobs";
import { problemOf } from "../../api/hooks/query";
import { cancelState, type JobSummary } from "../../api/jobs";
import { CancelJobAction } from "../../components/CancelJobAction";
import { EventLog } from "../../components/EventLog";
import { JobStatusLabel } from "../../components/JobStatusLabel";
import { LoadingView } from "../../components/LoadingView";
import { OutcomeCounts } from "../../components/OutcomeCounts";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { Section } from "../../components/Section";
import { StatusLabel } from "../../components/StatusLabel";
import { Timestamp } from "../../components/Timestamp";
import { UsageSummary } from "../../components/UsageSummary";
import { formatUsd } from "../../components/usd";
import { ExportActions } from "./ExportActions";
import { JobResults } from "./JobResults";
import { KIND_LABELS } from "./kinds";

function JobTimes({ job }: Readonly<{ job: JobSummary }>) {
  return (
    <Typography.Paragraph size="sm" color="muted">
      Job <Typography.Code>{job.id}</Typography.Code> · created <Timestamp value={job.created_at} />{" "}
      · started <Timestamp value={job.started_at} /> · finished{" "}
      <Timestamp value={job.finished_at} />
    </Typography.Paragraph>
  );
}

function JobView({ job }: Readonly<{ job: JobSummary }>) {
  // A cancel asked for ends the job once its claimed tasks end (SPEC-10 §4.2), which a dead worker's lease delays.
  const cancel = cancelState(job);
  return (
    <section className="flex flex-col gap-6">
      <PageHeader
        title={`${KIND_LABELS[job.kind]} job`}
        actions={cancel === "cancellable" ? <CancelJobAction id={job.id} /> : undefined}
      >
        <JobStatusLabel status={job.status} />
        {cancel === "requested" ? <StatusLabel text="cancel requested" tone="warning" /> : null}
      </PageHeader>
      <JobTimes job={job} />
      <Section title="Tasks">
        <OutcomeCounts counts={job.counts} outcomes={job.outcomes} />
      </Section>
      <Section title="Usage">
        <UsageSummary usage={job.usage} />
        <Typography.Paragraph size="sm">
          Estimated LLM cost:{" "}
          {job.llm_cost_usd === null
            ? "unknown, some of its tokens have no price"
            : formatUsd(job.llm_cost_usd)}
        </Typography.Paragraph>
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
