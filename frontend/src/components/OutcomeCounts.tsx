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
