import { Table, Typography } from "@heroui/react";
import { useId } from "react";
import type { StreamState } from "../api/events";
import { useJobEvents } from "../api/hooks/events";
import { ProblemAlert } from "./ProblemAlert";
import { StatusLabel, type StatusTone } from "./StatusLabel";

// One tone per stream state: receiving, waiting to reconnect (SPEC-12 §4.5), closed after the job's end, or refused.
const STATE_TONES: Record<StreamState, StatusTone> = {
  connecting: "neutral",
  live: "accent",
  reconnecting: "warning",
  ended: "success",
  failed: "danger",
};

/** A job's run events as they are stored (`GET /v1/jobs/{id}/events`), live until the job ends. Each event's data is
 * shown as the server sent it. A dropped stream, or one silent past two heartbeats, reconnects after the last event
 * received. */
export function EventLog({ jobId }: Readonly<{ jobId: string }>) {
  const { events, state, problem } = useJobEvents(jobId);
  const headingId = useId();
  const rows = events.map((event, index) => ({ key: String(index), ...event }));
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Typography.Heading level={2} id={headingId}>
          Events
        </Typography.Heading>
        <StatusLabel text={state} tone={STATE_TONES[state]} />
      </div>
      {problem === null ? null : <ProblemAlert problem={problem} />}
      <Table>
        <Table.ScrollContainer>
          <Table.Content aria-label="Events">
            <Table.Header>
              <Table.Column isRowHeader>Event</Table.Column>
              <Table.Column>ID</Table.Column>
              <Table.Column>Data</Table.Column>
            </Table.Header>
            <Table.Body
              items={rows}
              renderEmptyState={() => (
                <Typography.Paragraph color="muted">No event yet.</Typography.Paragraph>
              )}
            >
              {(event) => (
                <Table.Row id={event.key}>
                  <Table.Cell>{event.kind}</Table.Cell>
                  <Table.Cell>{event.id ?? "—"}</Table.Cell>
                  <Table.Cell>
                    <Typography.Code>{event.data}</Typography.Code>
                  </Table.Cell>
                </Table.Row>
              )}
            </Table.Body>
          </Table.Content>
        </Table.ScrollContainer>
      </Table>
    </section>
  );
}
