import { Table, Typography } from "@heroui/react";
import { ChevronRight } from "@gravity-ui/icons";
import type { ReactNode } from "react";
import type { JobSummary } from "../../api/jobs";
import { DurationText } from "../../components/ElapsedTime";
import { JobStatusLabel } from "../../components/JobStatusLabel";
import { TaskCountsText } from "../../components/OutcomeCounts";
import { Timestamp } from "../../components/Timestamp";
import { runPath } from "../playground/modes";
import { KIND_LABELS } from "./kinds";
import { jobPath } from "./paths";

/** What a run was started on: its start URL, or how many URLs it had. */
function target({ start_url, url_count }: JobSummary): string {
  if (start_url !== null) return start_url;
  const count = url_count ?? 0;
  return `${String(count)} ${count === 1 ? "URL" : "URLs"}`;
}

/** The last column's cue that a row opens its run: the whole row is the link (React Aria row `href`), so this is text,
 * not a second control. */
function OpenCue() {
  return (
    <span className="flex items-center justify-end gap-1 text-accent">
      Open
      <ChevronRight aria-hidden="true" />
    </span>
  );
}

/** A column a jobs table can show: its header and its cell. */
const COLUMNS = {
  kind: { header: "Kind", cell: (job: JobSummary): ReactNode => KIND_LABELS[job.kind] },
  target: { header: "Target", cell: target },
  status: { header: "Status", cell: (job: JobSummary) => <JobStatusLabel status={job.status} /> },
  tasks: { header: "Tasks", cell: (job: JobSummary) => <TaskCountsText counts={job.counts} /> },
  started: { header: "Started", cell: (job: JobSummary) => <Timestamp value={job.started_at} /> },
  created: { header: "Created", cell: (job: JobSummary) => <Timestamp value={job.created_at} /> },
  duration: {
    header: "Duration",
    cell: (job: JobSummary) => (
      <DurationText startedAt={job.started_at} finishedAt={job.finished_at} />
    ),
  },
  open: { header: "Open", cell: () => <OpenCue /> },
} satisfies Record<string, { header: string; cell: (job: JobSummary) => ReactNode }>;

export type JobColumn = keyof typeof COLUMNS;

/** Where a job's row goes: its run in its playground mode, or the job page for a kind no mode runs (SPEC-14 §4.8). */
function rowPath(job: JobSummary): string {
  return runPath(job.kind, job.id) ?? jobPath(job.id);
}

/** Jobs as table rows, newest first, in the `columns` given (each with its fixed width class, so long values truncate
 * rather than move the columns); a row opens its run. The first column is the row header. Recent runs and the Jobs
 * screen both list jobs with it. */
export function JobRows({
  label,
  jobs,
  columns,
  empty = null,
}: Readonly<{
  label: string;
  jobs: readonly JobSummary[];
  columns: readonly (readonly [JobColumn, string])[];
  /** What an empty list says; null when the caller says it instead. */
  empty?: string | null;
}>) {
  return (
    <Table>
      <Table.ScrollContainer>
        <Table.Content aria-label={label} className="table-fixed">
          <Table.Header>
            {columns.map(([id, width], i) => (
              <Table.Column key={id} id={id} isRowHeader={i === 0} className={width}>
                {/* The open cue's column is named for screen readers only: the cue says it in each row. */}
                {id === "open" ? (
                  <span className="sr-only">{COLUMNS[id].header}</span>
                ) : (
                  COLUMNS[id].header
                )}
              </Table.Column>
            ))}
          </Table.Header>
          <Table.Body
            items={jobs}
            {...(empty === null
              ? {}
              : {
                  renderEmptyState: () => (
                    <Typography.Paragraph color="muted">{empty}</Typography.Paragraph>
                  ),
                })}
          >
            {(job) => (
              <Table.Row id={job.id} href={rowPath(job)}>
                {columns.map(([id]) => (
                  <Table.Cell key={id} className="truncate">
                    {COLUMNS[id].cell(job)}
                  </Table.Cell>
                ))}
              </Table.Row>
            )}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}
