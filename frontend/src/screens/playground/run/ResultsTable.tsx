import { Button, Link, Table, Typography } from "@heroui/react";
import { useState, type Key } from "react";
import { useJobValues } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import type { JsonValuesItem } from "../../../api/jobs";
import { useCursorPages } from "../../../components/cursors";
import { OutcomeLabel } from "../../../components/OutcomeLabel";
import { PAGE_SIZE, PagedTable } from "../../../components/PagedTable";
import { ItemDrawer } from "./ItemDrawer";
import { ScrapeAsBatchBar, SelectionCheckbox, selectOnPage } from "./scrapeAsBatch";

/** A page of the job and its place in the job (from 1): tasks keep their order (oldest first), so the place is the
 * row's identity. */
interface Row {
  id: number;
  item: JsonValuesItem;
}

/** The name of a row's JSON button: the page's place in the job. */
function pageLabel({ id }: Row): string {
  return `JSON of page ${String(id)}`;
}

/** The selected URLs of a table that has row selection, and how they change. */
interface UrlSelection {
  selected: ReadonlySet<string>;
  onSelect: (selected: Set<string>) => void;
}

/** React Aria's selection props for `rows`, whose keys are their places: a row is selected when its URL is. */
function selectionProps(rows: readonly Row[], { selected, onSelect }: UrlSelection) {
  return {
    selectionMode: "multiple" as const,
    selectedKeys: new Set(rows.filter(({ item }) => selected.has(item.url)).map(({ id }) => id)),
    onSelectionChange: (selection: "all" | Set<Key>) => {
      const urls = rows.map(({ item }) => item.url);
      const chosen =
        selection === "all"
          ? selection
          : new Set(rows.filter(({ id }) => selection.has(id)).map(({ item }) => item.url));
      onSelect(selectOnPage(selected, urls, chosen));
    },
  };
}

function PagesTable({
  rows,
  selection,
  onOpen,
}: Readonly<{
  rows: readonly Row[];
  selection: UrlSelection | null;
  onOpen: (row: Row) => void;
}>) {
  return (
    <Table>
      <Table.ScrollContainer>
        {/* Fixed column widths: long URLs truncate rather than moving the columns. */}
        <Table.Content
          aria-label="Pages"
          className="table-fixed"
          {...(selection === null ? {} : selectionProps(rows, selection))}
        >
          <Table.Header>
            {selection === null ? null : (
              <Table.Column className="w-12">
                <SelectionCheckbox label="Select this page" />
              </Table.Column>
            )}
            <Table.Column isRowHeader>URL</Table.Column>
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
                {selection === null ? null : (
                  <Table.Cell>
                    <SelectionCheckbox label="Select" />
                  </Table.Cell>
                )}
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
                    aria-label={pageLabel(row)}
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
 * row's JSON opens in a drawer. The job's events read the page shown again as tasks end. With `selectable` (a crawl's
 * pages), rows are selected by URL across pages, and the selected URLs open as a batch (SPEC-14 §2.8). */
export function ResultsTable({
  jobId,
  withMetadata,
  selectable,
}: Readonly<{ jobId: string; withMetadata: boolean; selectable: boolean }>) {
  const { cursor, page, previous, nextTo } = useCursorPages();
  const values = useJobValues(jobId, { cursor, limit: PAGE_SIZE, withMetadata });
  const [open, setOpen] = useState<Row | null>(null);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const data = values.data;
  const first = (page - 1) * PAGE_SIZE + 1;
  const rows = (data?.items ?? []).map((item, offset) => ({ id: first + offset, item }));
  return (
    <>
      {selectable ? <ScrapeAsBatchBar selected={selected} /> : null}
      <PagedTable
        problem={problemOf(values.error)}
        loading={data === undefined ? "Loading the pages" : null}
        page={page}
        onPrevious={previous}
        onNext={data === undefined ? null : nextTo(data.next_cursor)}
      >
        <PagesTable
          rows={rows}
          selection={selectable ? { selected, onSelect: setSelected } : null}
          onOpen={setOpen}
        />
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
