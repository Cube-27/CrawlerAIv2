import { Table } from "@heroui/react";
import { useState, type ReactNode } from "react";
import { useJobs } from "../../api/hooks/jobs";
import { problemOf } from "../../api/hooks/query";
import type { JobFilters, JobKind, JobStatus, JobSummary } from "../../api/jobs";
import { useCursorPages } from "../../components/cursors";
import { EmptyView } from "../../components/EmptyView";
import { JobStatusLabel } from "../../components/JobStatusLabel";
import { LoadingView } from "../../components/LoadingView";
import { OptionSelect } from "../../components/OptionSelect";
import { TaskCountsText } from "../../components/OutcomeCounts";
import { ProblemAlert } from "../../components/ProblemAlert";
import { TablePagination } from "../../components/TablePagination";
import { KIND_LABELS } from "./kinds";
import { jobPath } from "./paths";

/** Jobs per page: the table's box (`h-table-page` in theme.css) holds this many rows. */
const PAGE_SIZE = 20;

/** The filter choice that sends no filter. */
const ANY = "any";

const KIND_OPTIONS: Readonly<Record<JobKind | typeof ANY, string>> = {
  [ANY]: "Any kind",
  ...KIND_LABELS,
};

// SPEC-01 §4.2: the statuses of a job, named as `JobStatusLabel` shows them.
const STATUS_OPTIONS: Readonly<Record<JobStatus | typeof ANY, string>> = {
  [ANY]: "Any status",
  queued: "queued",
  running: "running",
  completed: "completed",
  failed: "failed",
  cancelled: "cancelled",
};

function optionOf<K extends string>(options: Readonly<Record<K, string>>) {
  return (key: unknown): key is K => typeof key === "string" && key in options;
}

function orAny<K extends string>(value: K | null): K | typeof ANY {
  return value ?? ANY;
}

function JobFilterFields({
  filters,
  onChange,
}: Readonly<{ filters: JobFilters; onChange: (filters: JobFilters) => void }>) {
  return (
    <div className="flex flex-wrap gap-4">
      <OptionSelect
        label="Kind"
        options={KIND_OPTIONS}
        value={orAny(filters.kind)}
        accepts={optionOf(KIND_OPTIONS)}
        onChange={(kind) => {
          onChange({ ...filters, kind: kind === ANY ? null : kind });
        }}
      />
      <OptionSelect
        label="Status"
        options={STATUS_OPTIONS}
        value={orAny(filters.status)}
        accepts={optionOf(STATUS_OPTIONS)}
        onChange={(status) => {
          onChange({ ...filters, status: status === ANY ? null : status });
        }}
      />
    </div>
  );
}

function JobRows({ jobs }: Readonly<{ jobs: readonly JobSummary[] }>) {
  return (
    <Table>
      <Table.ScrollContainer>
        {/* Fixed column widths: a page of long values truncates rather than moving the columns. */}
        <Table.Content aria-label="Jobs" className="table-fixed">
          <Table.Header>
            <Table.Column isRowHeader className="w-1/6">
              Kind
            </Table.Column>
            <Table.Column className="w-1/6">Status</Table.Column>
            <Table.Column className="w-5/12">Tasks</Table.Column>
            <Table.Column className="w-1/4">Created</Table.Column>
          </Table.Header>
          <Table.Body items={jobs}>
            {(job) => (
              <Table.Row id={job.id} href={jobPath(job.id)}>
                <Table.Cell className="truncate">{KIND_LABELS[job.kind]}</Table.Cell>
                <Table.Cell>
                  <JobStatusLabel status={job.status} />
                </Table.Cell>
                <Table.Cell className="truncate">
                  <TaskCountsText counts={job.counts} />
                </Table.Cell>
                <Table.Cell className="truncate">{job.created_at}</Table.Cell>
              </Table.Row>
            )}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}

function isFiltered({ kind, status }: JobFilters): boolean {
  return kind !== null || status !== null;
}

/** One page of the jobs that pass `filters`. Every state (loading, problem, empty, rows) fills the same box and the
 * pager stays under it, so paging moves nothing (owner's rule: no layout shift on interaction). */
function JobPages({ filters }: Readonly<{ filters: JobFilters }>) {
  const { cursor, page, previous, nextTo } = useCursorPages();
  const jobs = useJobs({ filters, cursor, limit: PAGE_SIZE });
  const problem = problemOf(jobs.error);
  let content: ReactNode;
  if (problem !== null) content = <ProblemAlert problem={problem} />;
  else if (!jobs.isSuccess) content = <LoadingView label="Loading jobs" />;
  else if (jobs.data.items.length === 0 && previous === null) {
    content = isFiltered(filters) ? (
      <EmptyView title="No job matches these filters">Choose another kind or status.</EmptyView>
    ) : (
      <EmptyView title="No jobs yet">Start a batch, crawl or extract above.</EmptyView>
    );
  } else content = <JobRows jobs={jobs.data.items} />;
  return (
    <>
      <div className="h-table-page overflow-auto">{content}</div>
      <TablePagination
        summary={`Page ${String(page)}`}
        onPrevious={previous}
        onNext={jobs.isSuccess ? nextTo(jobs.data.next_cursor) : null}
      />
    </>
  );
}

/** The jobs, newest first (`GET /v1/jobs`), filtered by kind and status, a page at a time; a row opens its job. */
export function JobTable() {
  const [filters, setFilters] = useState<JobFilters>({ kind: null, status: null });
  return (
    <div className="flex flex-col gap-3">
      <JobFilterFields filters={filters} onChange={setFilters} />
      {/* Keyed by the filters: other filters page from their own first page. */}
      <JobPages key={`${String(filters.kind)}/${String(filters.status)}`} filters={filters} />
    </div>
  );
}
