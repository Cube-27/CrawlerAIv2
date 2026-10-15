import { Link, Table } from "@heroui/react";
import { useState } from "react";
import { PAGE_SIZE, PagedTable } from "../../../components/PagedTable";

/** The URLs a map found (SPEC-14 §4.3), a page at a time in the order the server returned them. The whole list is in
 * the map's answer, so the pages are slices of it. */
export function LinksTable({ urls }: Readonly<{ urls: readonly string[] }>) {
  const [page, setPage] = useState(1);
  const first = (page - 1) * PAGE_SIZE;
  const rows = urls.slice(first, first + PAGE_SIZE).map((url) => ({ id: url, url }));
  return (
    <PagedTable
      problem={null}
      loading={null}
      page={page}
      onPrevious={
        page > 1
          ? () => {
              setPage(page - 1);
            }
          : null
      }
      onNext={
        first + PAGE_SIZE < urls.length
          ? () => {
              setPage(page + 1);
            }
          : null
      }
    >
      <Table>
        <Table.ScrollContainer>
          {/* One fixed column: long URLs truncate rather than widening the table. */}
          <Table.Content aria-label="Links" className="table-fixed">
            <Table.Header>
              <Table.Column isRowHeader className="w-full">
                URL
              </Table.Column>
            </Table.Header>
            <Table.Body items={rows}>
              {(row) => (
                <Table.Row id={row.id}>
                  <Table.Cell className="truncate">
                    {/* The page itself, in a new tab: it is another site, not a screen of this app. */}
                    <Link href={row.url} target="_blank" rel="noreferrer">
                      {row.url}
                    </Link>
                  </Table.Cell>
                </Table.Row>
              )}
            </Table.Body>
          </Table.Content>
        </Table.ScrollContainer>
      </Table>
    </PagedTable>
  );
}
