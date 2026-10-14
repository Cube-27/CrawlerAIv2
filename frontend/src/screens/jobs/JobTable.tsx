import { Table } from "@heroui/react";
import { useSearchParams } from "react-router";
import { useJobs } from "../../api/hooks/jobs";
import { problemOf } from "../../api/hooks/query";
import type { JobFilters, JobKind, JobStatus, JobSummary } from "../../api/jobs";
import { useCursorPages } from "../../components/cursors";
import { EmptyView } from "../../components/EmptyView";
import { JOB_STATUS_TEXT, JobStatusLabel } from "../../components/JobStatusLabel";
import { isOptionOf, OptionSelect } from "../../components/OptionSelect";
import { TaskCountsText } from "../../components/OutcomeCounts";
import { PAGE_SIZE, PagedTable } from "../../components/PagedTable";
import { KIND_LABELS } from "./kinds";
import { jobPath } from "./paths";

/** The filter choice that sends no filter. */
const ANY = "any";

const KIND_OPTIONS: Readonly<Record<JobKind | typeof ANY, string>> = {
  [ANY]: "Any kind",
  ...KIND_LABELS,
};

const STATUS_OPTIONS: Readonly<Record<JobStatus | typeof ANY, string>> = {
  [ANY]: "Any status",
  ...JOB_STATUS_TEXT,
};

const isKindOption = isOptionOf(KIND_OPTIONS);
const isStatusOption = isOptionOf(STATUS_OPTIONS);
const isKind = isOptionOf(KIND_LABELS);
const isStatus = isOptionOf(JOB_STATUS_TEXT);

// The filters live in the address, as the records screen's do: going back to the list keeps them.
function filtersOf(params: URLSearchParams): JobFilters {
  const kind = params.get("kind");
  const status = params.get("status");
  return { kind: isKind(kind) ? kind : null, status: isStatus(status) ? status : null };
}

function paramsOf({ kind, status }: JobFilters): Record<string, string> {
  return { ...(kind === null ? {} : { kind }), ...(status === null ? {} : { status }) };
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
        value={filters.kind ?? ANY}
        accepts={isKindOption}
        onChange={(kind) => {
          onChange({ ...filters, kind: kind === ANY ? null : kind });
        }}
      />
      <OptionSelect
        label="Status"
        options={STATUS_OPTIONS}
        value={filters.status ?? ANY}
        accepts={isStatusOption}
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

/** The page's rows; an empty first page says why there are none. */
function JobPageContent({
  jobs,
  filters,
  first,
}: Readonly<{ jobs: readonly JobSummary[]; filters: JobFilters; first: boolean }>) {
  if (jobs.length > 0 || !first) return <JobRows jobs={jobs} />;
  if (filters.kind !== null || filters.status !== null) {
    return (
      <EmptyView title="No job matches these filters">Choose another kind or status.</EmptyView>
    );
  }
  return <EmptyView title="No jobs yet">Start a batch, crawl or extract above.</EmptyView>;
}

/** One page of the jobs that pass `filters`. */
function JobPages({ filters }: Readonly<{ filters: JobFilters }>) {
  const { cursor, page, previous, nextTo } = useCursorPages();
  const jobs = useJobs({ filters, cursor, limit: PAGE_SIZE });
  return (
    <PagedTable
      problem={problemOf(jobs.error)}
      loading={jobs.isSuccess ? null : "Loading jobs"}
      page={page}
      onPrevious={previous}
      onNext={jobs.isSuccess ? nextTo(jobs.data.next_cursor) : null}
    >
      {jobs.isSuccess ? (
        <JobPageContent jobs={jobs.data.items} filters={filters} first={previous === null} />
      ) : null}
    </PagedTable>
  );
}

/** The jobs, newest first (`GET /v1/jobs`), filtered by kind and status, a page at a time; a row opens its job. */
export function JobTable() {
  const [params, setParams] = useSearchParams();
  const filters = filtersOf(params);
  return (
    <div className="flex flex-col gap-3">
      <JobFilterFields
        filters={filters}
        onChange={(next) => {
          setParams(paramsOf(next), { replace: true });
        }}
      />
      {/* Keyed by the filters: other filters page from their own first page. */}
      <JobPages key={`${String(filters.kind)}/${String(filters.status)}`} filters={filters} />
    </div>
  );
}
