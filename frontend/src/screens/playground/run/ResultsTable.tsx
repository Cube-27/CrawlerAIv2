import { Button, Link, Table, Typography } from "@heroui/react";
import { useState } from "react";
import { useJobValues } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import type { JsonValuesItem } from "../../../api/jobs";
import { useCursorPages } from "../../../components/cursors";
import { OutcomeLabel } from "../../../components/OutcomeLabel";
import { PAGE_SIZE, PagedTable } from "../../../components/PagedTable";
import { ItemDrawer } from "./ItemDrawer";

/** A page of the job and its place in the job (from 1): tasks keep their order (oldest first), so the place is the
 * row's identity. */
interface Row {
  id: number;
  item: JsonValuesItem;
}

function PagesTable({
  rows,
  onOpen,
}: Readonly<{ rows: readonly Row[]; onOpen: (row: Row) => void }>) {
  return (
    <Table>
      <Table.ScrollContainer>
        {/* Fixed column widths: long URLs truncate rather than moving the columns. */}
        <Table.Content aria-label="Pages" className="table-fixed">
          <Table.Header>
            <Table.Column isRowHeader className="w-1/2">
              URL
            </Table.Column>
            <Table.Column className="w-1/6">Outcome</Table.Column>
            <Table.Column className="w-1/6">Records</Table.Column>
            <Table.Column className="w-1/6">JSON</Table.Column>
          </Table.Header>
          <Table.Body
            items={rows}
            renderEmptyState={() => (
              <Typography.Paragraph color="muted">No page has a result yet.</Typography.Paragraph>
            )}
          >
            {(row) => (
              <Table.Row id={row.id}>
                <Table.Cell className="truncate">
                  {/* The page itself, in a new tab: it is another site, not a screen of this app. */}
                  <Link href={row.item.url} target="_blank" rel="noreferrer">
                    {row.item.url}
                  </Link>
                </Table.Cell>
                <Table.Cell>
                  {row.item.outcome === null ? "—" : <OutcomeLabel outcome={row.item.outcome} />}
                </Table.Cell>
                <Table.Cell>{row.item.records.length}</Table.Cell>
                <Table.Cell>
                  <Button
                    size="sm"
                    variant="secondary"
                    aria-label={`JSON of page ${String(row.id)}`}
                    onPress={() => {
                      onOpen(row);
                    }}
                  >
                    JSON
                  </Button>
                </Table.Cell>
              </Table.Row>
            )}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}

/** A batch's or crawl's pages (SPEC-14 §4.3), one row each in task order, from `results?format=json_values`; each
 * row's JSON opens in a drawer. The job's events read the page shown again as tasks end. */
export function ResultsTable({
  jobId,
  withMetadata,
}: Readonly<{ jobId: string; withMetadata: boolean }>) {
  const { cursor, page, previous, nextTo } = useCursorPages();
  const values = useJobValues(jobId, { cursor, limit: PAGE_SIZE, withMetadata });
  const [open, setOpen] = useState<Row | null>(null);
  const data = values.data;
  const first = (page - 1) * PAGE_SIZE + 1;
  const rows = (data?.items ?? []).map((item, offset) => ({ id: first + offset, item }));
  return (
    <>
      <PagedTable
        problem={problemOf(values.error)}
        loading={data === undefined ? "Loading the pages" : null}
        page={page}
        onPrevious={previous}
        onNext={data === undefined ? null : nextTo(data.next_cursor)}
      >
        <PagesTable rows={rows} onOpen={setOpen} />
      </PagedTable>
      {open === null ? null : (
        <ItemDrawer
          item={open.item}
          position={open.id}
          onClose={() => {
            setOpen(null);
          }}
        />
      )}
    </>
  );
}
