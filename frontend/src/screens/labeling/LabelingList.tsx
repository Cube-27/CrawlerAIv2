import { Chip, Table } from "@heroui/react";
import { useLoaderData } from "react-router";
import { EvalUiOff } from "./EvalUiOff";
import type { listLoader, PageSummary } from "./loaders";

export function statusText(status: PageSummary["status"]): string {
  return status ?? "not labeled";
}

export function pageHref({ id }: PageSummary): string {
  return `/labeling/${id}`;
}

export function SplitBadge({ split }: { split: PageSummary["split"] }) {
  // The API serves dev only (D-0207); a private-split badge comes with hidden/fresh labeling (D-0214).
  return <Chip>Split: {split}</Chip>;
}

export function LabelingList() {
  const data = useLoaderData<typeof listLoader>();

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">Labeling</h1>
        <SplitBadge split="dev" />
      </div>
      {data.kind === "off" ? (
        <EvalUiOff />
      ) : data.pages.length === 0 ? (
        <p className="text-muted">
          No dev pages yet. Capture some with <code>crawlerai eval capture --split dev</code>.
        </p>
      ) : (
        <Table>
          <Table.ScrollContainer>
            <Table.Content aria-label="Dev eval pages">
              <Table.Header>
                <Table.Column isRowHeader>Page</Table.Column>
                <Table.Column>Schema</Table.Column>
                <Table.Column>Kind</Table.Column>
                <Table.Column>Category</Table.Column>
                <Table.Column>Status</Table.Column>
                <Table.Column>Labeler</Table.Column>
                <Table.Column>Checker</Table.Column>
              </Table.Header>
              <Table.Body items={data.pages}>
                {(page) => (
                  <Table.Row id={page.id} href={pageHref(page)}>
                    <Table.Cell>{page.id}</Table.Cell>
                    <Table.Cell>{page.schema_name}</Table.Cell>
                    <Table.Cell>{page.page_kind}</Table.Cell>
                    <Table.Cell>{page.category}</Table.Cell>
                    <Table.Cell>{statusText(page.status)}</Table.Cell>
                    <Table.Cell>{page.labeler ?? "—"}</Table.Cell>
                    <Table.Cell>{page.checker ?? "—"}</Table.Cell>
                  </Table.Row>
                )}
              </Table.Body>
            </Table.Content>
          </Table.ScrollContainer>
        </Table>
      )}
    </section>
  );
}
