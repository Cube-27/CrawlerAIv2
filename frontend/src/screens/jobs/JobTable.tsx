import { Table } from "@heroui/react";
import { useJobs } from "../../api/hooks/jobs";
import { problemOf } from "../../api/hooks/query";
import type { JobSummary } from "../../api/jobs";
import { useCursorPages } from "../../components/cursors";
import { EmptyView } from "../../components/EmptyView";
import { JobStatusLabel } from "../../components/JobStatusLabel";
import { LoadingView } from "../../components/LoadingView";
import { TaskCountsText } from "../../components/OutcomeCounts";
import { ProblemAlert } from "../../components/ProblemAlert";
import { TablePagination } from "../../components/TablePagination";
import { KIND_LABELS } from "./kinds";
import { jobPath } from "./paths";

function JobRows({ jobs }: Readonly<{ jobs: readonly JobSummary[] }>) {
  return (
    <Table>
      <Table.ScrollContainer>
        <Table.Content aria-label="Jobs">
          <Table.Header>
            <Table.Column isRowHeader>Kind</Table.Column>
            <Table.Column>Status</Table.Column>
            <Table.Column>Tasks</Table.Column>
            <Table.Column>Created</Table.Column>
          </Table.Header>
          <Table.Body items={jobs}>
            {(job) => (
              <Table.Row id={job.id} href={jobPath(job.id)}>
                <Table.Cell>{KIND_LABELS[job.kind]}</Table.Cell>
                <Table.Cell>
                  <JobStatusLabel status={job.status} />
                </Table.Cell>
                <Table.Cell>
                  <TaskCountsText counts={job.counts} />
                </Table.Cell>
                <Table.Cell>{job.created_at}</Table.Cell>
              </Table.Row>
            )}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}

/** The jobs, newest first (`GET /v1/jobs`), a page at a time; a row opens its job. */
export function JobTable() {
  const { cursor, page, previous, nextTo } = useCursorPages();
  const jobs = useJobs(cursor);
  const problem = problemOf(jobs.error);
  if (problem !== null) return <ProblemAlert problem={problem} />;
  if (!jobs.isSuccess) return <LoadingView label="Loading jobs" />;
  const { items, next_cursor } = jobs.data;
  if (items.length === 0 && previous === null) {
    return <EmptyView title="No jobs yet">Start a batch, crawl or extract above.</EmptyView>;
  }
  return (
    <div className="flex flex-col gap-3">
      <JobRows jobs={items} />
      <TablePagination
        summary={`Page ${String(page)}`}
        onPrevious={previous}
        onNext={nextTo(next_cursor)}
      />
    </div>
  );
}
