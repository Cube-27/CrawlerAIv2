import { Chip, Table, Typography } from "@heroui/react";
import { problemOf } from "../../api/hooks/query";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { EmptyView } from "../../components/EmptyView";
import { StatusLabel, type StatusTone } from "../../components/StatusLabel";
import { EvalUiOff } from "./EvalUiOff";
import { useEvalPages, type PageSummary } from "./queries";

export function statusText(status: PageSummary["status"]): string {
  return status ?? "not labeled";
}

// One tone per label status (DESIGN.md, Patterns: status display).
const STATUS_TONES: Record<NonNullable<PageSummary["status"]> | "none", StatusTone> = {
  none: "neutral",
  draft: "warning",
  labeled: "accent",
  checked: "success",
};

export function LabelStatusChip({ status }: Readonly<{ status: PageSummary["status"] }>) {
  return <StatusLabel text={statusText(status)} tone={STATUS_TONES[status ?? "none"]} />;
}

export function pageHref({ id }: PageSummary): string {
  return `/labeling/${id}`;
}

export function SplitBadge({ split }: Readonly<{ split: PageSummary["split"] }>) {
  // The API serves dev only (D-0207); a private-split badge comes with hidden/fresh labeling (D-0214).
  return <Chip>Split: {split}</Chip>;
}

/** The dev pages, or what to do when there are none yet. */
function PageList({ pages }: Readonly<{ pages: PageSummary[] }>) {
  if (pages.length === 0) {
    return (
      <EmptyView title="No dev pages yet">
        Capture some with <Typography.Code>crawlerai eval capture --split dev</Typography.Code>.
      </EmptyView>
    );
  }
  return (
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
          <Table.Body items={pages}>
            {(page) => (
              <Table.Row id={page.id} href={pageHref(page)}>
                <Table.Cell>{page.id}</Table.Cell>
                <Table.Cell>{page.schema_name}</Table.Cell>
                <Table.Cell>{page.page_kind}</Table.Cell>
                <Table.Cell>{page.category}</Table.Cell>
                <Table.Cell>
                  <LabelStatusChip status={page.status} />
                </Table.Cell>
                <Table.Cell>{page.labeler ?? "—"}</Table.Cell>
                <Table.Cell>{page.checker ?? "—"}</Table.Cell>
              </Table.Row>
            )}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}

export function LabelingList() {
  const pages = useEvalPages();

  return (
    <section className="flex flex-col gap-stack">
      <PageHeader title="Labeling">
        <SplitBadge split="dev" />
      </PageHeader>
      <PageListBody query={pages} />
    </section>
  );
}

function PageListBody({ query }: Readonly<{ query: ReturnType<typeof useEvalPages> }>) {
  const problem = problemOf(query.error);
  if (problem !== null) return <ProblemAlert problem={problem} />;
  if (!query.isSuccess) return <LoadingView label="Loading eval pages" />;
  return query.data.kind === "off" ? <EvalUiOff /> : <PageList pages={query.data.pages} />;
}
