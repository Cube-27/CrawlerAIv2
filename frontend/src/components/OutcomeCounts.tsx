import { Table, Typography } from "@heroui/react";
import type { OutcomeCounts as Outcomes, TaskCounts, TaskOutcome, TaskStatus } from "../api/jobs";
import { TaskStatusLabel } from "./JobStatusLabel";
import { OutcomeLabel } from "./OutcomeLabel";

// In the order a task goes through them (SPEC-01 §4.2), and the outcomes as ARCHITECTURE §6 lists them.
const STATUSES: readonly TaskStatus[] = ["queued", "claimed", "done", "failed", "cancelled"];
const OUTCOMES: readonly TaskOutcome[] = [
  "extracted",
  "partial",
  "unchanged",
  "links_only",
  "blocked",
  "shell",
  "not_found",
  "no_match",
  "failed",
];

/** A job's tasks in one line: their total, then each status some task has, as "3 tasks: 1 queued, 2 done". */
export function TaskCountsText({ counts }: Readonly<{ counts: TaskCounts }>) {
  const total = STATUSES.reduce((sum, status) => sum + counts[status], 0);
  const parts = STATUSES.filter((status) => counts[status] > 0).map(
    (status) => `${String(counts[status])} ${status}`,
  );
  const tasks = `${String(total)} ${total === 1 ? "task" : "tasks"}`;
  return <>{parts.length === 0 ? tasks : `${tasks}: ${parts.join(", ")}`}</>;
}

/** A job's tasks by status, and by outcome for those that have one (SPEC-10 §4.2). Outcomes no task has are left
 * out. */
export function OutcomeCounts({
  counts,
  outcomes,
}: Readonly<{ counts: TaskCounts; outcomes: Outcomes }>) {
  const statuses = STATUSES.map((status) => ({ id: status, count: counts[status] }));
  const reached = OUTCOMES.filter((outcome) => outcomes[outcome] > 0).map((outcome) => ({
    id: outcome,
    count: outcomes[outcome],
  }));
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Table>
        <Table.ScrollContainer>
          <Table.Content aria-label="Tasks by status">
            <Table.Header>
              <Table.Column isRowHeader>Status</Table.Column>
              <Table.Column>Tasks</Table.Column>
            </Table.Header>
            <Table.Body items={statuses}>
              {({ id, count }) => (
                <Table.Row id={id}>
                  <Table.Cell>
                    <TaskStatusLabel status={id} />
                  </Table.Cell>
                  <Table.Cell>{count}</Table.Cell>
                </Table.Row>
              )}
            </Table.Body>
          </Table.Content>
        </Table.ScrollContainer>
      </Table>
      <Table>
        <Table.ScrollContainer>
          <Table.Content aria-label="Tasks by outcome">
            <Table.Header>
              <Table.Column isRowHeader>Outcome</Table.Column>
              <Table.Column>Tasks</Table.Column>
            </Table.Header>
            <Table.Body
              items={reached}
              renderEmptyState={() => (
                <Typography.Paragraph color="muted">
                  No task has an outcome yet.
                </Typography.Paragraph>
              )}
            >
              {({ id, count }) => (
                <Table.Row id={id}>
                  <Table.Cell>
                    <OutcomeLabel outcome={id} />
                  </Table.Cell>
                  <Table.Cell>{count}</Table.Cell>
                </Table.Row>
              )}
            </Table.Body>
          </Table.Content>
        </Table.ScrollContainer>
      </Table>
    </div>
  );
}

/** A job's outcomes on one line, each outcome some task reached with its count (the run header's summary, D-0975), or
 * a muted line while none has. */
export function OutcomeSummary({ outcomes }: Readonly<{ outcomes: Outcomes }>) {
  const reached = OUTCOMES.filter((outcome) => outcomes[outcome] > 0);
  if (reached.length === 0) {
    return (
      <Typography.Paragraph size="sm" color="muted">
        No outcome yet
      </Typography.Paragraph>
    );
  }
  return (
    <ul aria-label="Outcomes" className="flex flex-wrap items-center gap-x-4 gap-y-2">
      {reached.map((outcome) => (
        <li key={outcome} className="flex items-center gap-1.5">
          <OutcomeLabel outcome={outcome} />
          <Typography.Paragraph size="sm" weight="medium">
            {outcomes[outcome]}
          </Typography.Paragraph>
        </li>
      ))}
    </ul>
  );
}
