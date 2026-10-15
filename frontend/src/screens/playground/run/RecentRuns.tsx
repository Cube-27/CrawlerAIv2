import { Table, Typography } from "@heroui/react";
import { useJobs } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import type { JobKind, JobSummary } from "../../../api/jobs";
import { JobStatusLabel } from "../../../components/JobStatusLabel";
import { LoadingView } from "../../../components/LoadingView";
import { ProblemAlert } from "../../../components/ProblemAlert";
import { Timestamp } from "../../../components/Timestamp";
import { runPath } from "../modes";

/** How many runs the list shows (SPEC-14 §4.6). */
const RECENT = 10;

/** What a run was started on: its start URL, or how many URLs it had. */
function target({ start_url, url_count }: JobSummary): string {
  if (start_url !== null) return start_url;
  const count = url_count ?? 0;
  return `${String(count)} ${count === 1 ? "URL" : "URLs"}`;
}

/** The row's link: the run in its mode. */
function runLink(job: JobSummary): { href?: string } {
  const href = runPath(job.kind, job.id);
  return href === null ? {} : { href };
}

function RunRows({ jobs }: Readonly<{ jobs: readonly JobSummary[] }>) {
  return (
    <Table>
      <Table.ScrollContainer>
        {/* Fixed column widths: long URLs truncate rather than moving the columns. */}
        <Table.Content aria-label="Recent runs" className="table-fixed">
          <Table.Header>
            <Table.Column isRowHeader className="w-1/2">
              Run
            </Table.Column>
            <Table.Column className="w-1/4">Status</Table.Column>
            <Table.Column className="w-1/4">Started</Table.Column>
          </Table.Header>
          <Table.Body
            items={jobs}
            renderEmptyState={() => (
              <Typography.Paragraph color="muted">No runs yet.</Typography.Paragraph>
            )}
          >
            {(job) => (
              <Table.Row id={job.id} {...runLink(job)}>
                <Table.Cell className="truncate">{target(job)}</Table.Cell>
                <Table.Cell>
                  <JobStatusLabel status={job.status} />
                </Table.Cell>
                <Table.Cell className="truncate">
                  <Timestamp value={job.started_at} />
                </Table.Cell>
              </Table.Row>
            )}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}

/** The last runs of a mode's `kind` (SPEC-14 §4.6), newest first, shown before any run on the page; a row opens its
 * run here (`?job=`). Every state fills the output area's box, so a run that replaces the list moves nothing. */
export function RecentRuns({ kind }: Readonly<{ kind: JobKind }>) {
  const jobs = useJobs({ filters: { kind, status: null }, cursor: null, limit: RECENT });
  const problem = problemOf(jobs.error);
  let content;
  if (problem !== null) content = <ProblemAlert problem={problem} />;
  else if (jobs.isSuccess) content = <RunRows jobs={jobs.data.items} />;
  else content = <LoadingView label="Loading recent runs" />;
  return (
    <section aria-label="Recent runs" className="flex min-h-playground-output flex-col gap-3">
      <Typography.Heading level={2}>Recent runs</Typography.Heading>
      {content}
    </section>
  );
}
