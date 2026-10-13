import { Table, Typography } from "@heroui/react";
import type { FieldTypes } from "../api/field";
import type { RecordField, ScrapeRecord } from "../api/scrape";
import { ConfidenceCell, confidenceText } from "./ConfidenceCell";
import { EmptyView } from "./EmptyView";
import { FieldStatusBadge } from "./FieldStatusBadge";
import { FieldValue } from "./FieldValue";
import { LocatorText } from "./LocatorText";
import { StatusLabel } from "./StatusLabel";

/** Whether a record is complete, with its mode and confidence. */
export function RecordSummary({ record }: Readonly<{ record: ScrapeRecord }>) {
  return (
    <>
      <StatusLabel
        text={record.complete ? "complete" : "incomplete"}
        tone={record.complete ? "success" : "warning"}
      />
      <Typography.Paragraph size="sm" color="muted">
        Mode {record.mode} · confidence {confidenceText(record.confidence)}
      </Typography.Paragraph>
    </>
  );
}

/** One record's fields, one row each, with every `field_meta` attribute the API returns (SPEC-07 §4.4). */
export function RecordFieldsTable({
  label,
  record,
  fieldTypes,
}: Readonly<{ label: string; record: ScrapeRecord; fieldTypes: FieldTypes }>) {
  const fields: (RecordField & { name: string })[] = Object.entries(record.fields).map(
    ([name, field]) => ({ ...field, name }),
  );
  return (
    <Table>
      <Table.ScrollContainer>
        <Table.Content aria-label={label}>
          <Table.Header>
            <Table.Column isRowHeader>Field</Table.Column>
            <Table.Column>Value</Table.Column>
            <Table.Column>Status</Table.Column>
            <Table.Column>Confidence</Table.Column>
            <Table.Column>Evidence</Table.Column>
            <Table.Column>Source</Table.Column>
            <Table.Column>Locator</Table.Column>
            <Table.Column>Derived by</Table.Column>
          </Table.Header>
          <Table.Body items={fields}>
            {(field) => (
              <Table.Row id={field.name}>
                <Table.Cell>{field.name}</Table.Cell>
                <Table.Cell>
                  <FieldValue field={field} spec={fieldTypes[field.name] ?? null} />
                </Table.Cell>
                <Table.Cell>
                  <FieldStatusBadge status={field.status} />
                </Table.Cell>
                <Table.Cell>
                  <ConfidenceCell confidence={field.confidence} calibrated={field.calibrated} />
                </Table.Cell>
                <Table.Cell>{field.evidence ?? "—"}</Table.Cell>
                <Table.Cell>{field.source_kind ?? "—"}</Table.Cell>
                <Table.Cell>
                  <LocatorText locator={field.locator} />
                </Table.Cell>
                <Table.Cell>{field.derived_by ?? "—"}</Table.Cell>
              </Table.Row>
            )}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}

/** Records extracted from one page, each with its fields, or why there are none. */
export function RecordList({
  records,
  fieldTypes,
}: Readonly<{ records: readonly ScrapeRecord[]; fieldTypes: FieldTypes }>) {
  if (records.length === 0) {
    return <EmptyView title="No records">The page yielded no record for this schema.</EmptyView>;
  }
  return (
    <div className="flex flex-col gap-6">
      {records.map((record, index) => {
        const title = `Record ${String(index + 1)}`;
        return (
          <section key={record.id} className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-3">
              <Typography.Heading level={3}>{title}</Typography.Heading>
              <RecordSummary record={record} />
            </div>
            <RecordFieldsTable label={`${title} fields`} record={record} fieldTypes={fieldTypes} />
          </section>
        );
      })}
    </div>
  );
}
