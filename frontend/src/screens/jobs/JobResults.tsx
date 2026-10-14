import { Table } from "@heroui/react";
import { useMemo, useState } from "react";
import { parseFieldTypes } from "../../api/field";
import { useJobResults } from "../../api/hooks/jobs";
import { problemOf } from "../../api/hooks/query";
import { useSchema } from "../../api/hooks/schemas";
import type { PageOutput } from "../../api/jobs";
import type { StoredRecord } from "../../api/records";
import { useCursorPages } from "../../components/cursors";
import { EmptyView } from "../../components/EmptyView";
import { TaskStatusLabel } from "../../components/JobStatusLabel";
import { LoadingView } from "../../components/LoadingView";
import { OutcomeLabel } from "../../components/OutcomeLabel";
import { ProblemAlert } from "../../components/ProblemAlert";
import { RecordTable } from "../../components/RecordTable";
import { TablePagination } from "../../components/TablePagination";
import { RecordInspector } from "../records/RecordInspector";

/** The job's records in the columns of their schema, each opening the record inspector. */
function JobRecords({ records }: Readonly<{ records: readonly StoredRecord[] }>) {
  const [open, setOpen] = useState<StoredRecord | null>(null);
  // A job extracts with one schema version (ARCHITECTURE §6 `job.schema_id`).
  const schema = useSchema(records[0]?.schema_id ?? null);
  const fieldTypes = useMemo(() => parseFieldTypes(schema.data?.fields), [schema.data]);
  const problem = problemOf(schema.error);
  if (records.length === 0) return <EmptyView title="No records yet" />;
  if (problem !== null) return <ProblemAlert problem={problem} />;
  if (!schema.isSuccess) return <LoadingView label="Loading the schema" />;
  return (
    <>
      <RecordTable label="Records" records={records} fieldTypes={fieldTypes} onOpen={setOpen} />
      {open === null ? null : (
        <RecordInspector
          key={open.id}
          record={open}
          fieldTypes={fieldTypes}
          onClose={() => {
            setOpen(null);
          }}
        />
      )}
    </>
  );
}

/** A job without a schema: each of its pages with its status and outcome. */
function PageOutputs({ pages }: Readonly<{ pages: readonly PageOutput[] }>) {
  return (
    <Table>
      <Table.ScrollContainer>
        <Table.Content aria-label="Pages">
          <Table.Header>
            <Table.Column isRowHeader>URL</Table.Column>
            <Table.Column>Status</Table.Column>
            <Table.Column>Outcome</Table.Column>
            <Table.Column>Fetched</Table.Column>
          </Table.Header>
          <Table.Body items={pages.map((page) => ({ id: page.task_id, page }))}>
            {({ id, page }) => (
              <Table.Row id={id}>
                <Table.Cell>{page.final_url ?? page.url}</Table.Cell>
                <Table.Cell>
                  <TaskStatusLabel status={page.status} />
                </Table.Cell>
                <Table.Cell>
                  {page.outcome === null ? "—" : <OutcomeLabel outcome={page.outcome} />}
                </Table.Cell>
                <Table.Cell>{page.fetched_at ?? "—"}</Table.Cell>
              </Table.Row>
            )}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}

/** One page of the job's results (`GET /v1/jobs/{id}/results`) with previous and next: its records, or the pages of a
 * job without a schema. */
export function JobResults({ jobId }: Readonly<{ jobId: string }>) {
  const { cursor, page, previous, nextTo } = useCursorPages();
  const results = useJobResults(jobId, cursor);
  const problem = problemOf(results.error);
  if (problem !== null) return <ProblemAlert problem={problem} />;
  if (!results.isSuccess) return <LoadingView label="Loading results" />;
  const { data } = results;
  return (
    <div className="flex flex-col gap-3">
      {data.kind === "records" ? (
        <JobRecords records={data.page.items} />
      ) : (
        <PageOutputs pages={data.page.items} />
      )}
      <TablePagination
        summary={`Page ${String(page)}`}
        onPrevious={previous}
        onNext={nextTo(data.page.next_cursor)}
      />
    </div>
  );
}
