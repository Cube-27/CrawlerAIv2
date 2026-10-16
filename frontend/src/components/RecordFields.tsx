import { Table, Typography } from "@heroui/react";
import type { FieldTypes } from "../api/field";
import type { ExtractedRecord } from "../api/records";
import type { RecordField } from "../api/scrape";
import { ConfidenceCell, confidenceText } from "./ConfidenceCell";
import { EmptyView } from "./EmptyView";
import { FieldStatusBadge } from "./FieldStatusBadge";
import { FieldValue } from "./FieldValue";
import { LocatorText } from "./LocatorText";
import { StatusLabel } from "./StatusLabel";

/** Whether a record is complete, with its mode and confidence. */
export function RecordSummary({ record }: Readonly<{ record: ExtractedRecord }>) {
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
}: Readonly<{ label: string; record: ExtractedRecord; fieldTypes: FieldTypes }>) {
  const fields: (RecordField & { name: string })[] = Object.entries(record.fields).map(
    ([name, field]) => ({ ...field, name }),
  );
  return (
    <Table>
      <Table.ScrollContainer>
        {/* Fixed column widths: a long value or locator truncates rather than pushing Evidence off the table. */}
        <Table.Content aria-label={label} className="table-fixed">
          <Table.Header>
            <Table.Column isRowHeader className="w-1/8">
              Field
            </Table.Column>
            <Table.Column className="w-1/4">Value</Table.Column>
            <Table.Column className="w-1/8">Status</Table.Column>
            <Table.Column className="w-1/8">Confidence</Table.Column>
            <Table.Column className="w-1/8">Evidence</Table.Column>
            <Table.Column className="w-1/12">Source</Table.Column>
            <Table.Column className="w-1/12">Locator</Table.Column>
            <Table.Column className="w-1/12">Derived by</Table.Column>
          </Table.Header>
          <Table.Body items={fields}>
            {(field) => (
              <Table.Row id={field.name}>
                <Table.Cell className="truncate">{field.name}</Table.Cell>
                <Table.Cell className="truncate">
                  {/* The status has its own column. */}
                  <FieldValue
                    field={field}
                    spec={fieldTypes[field.name] ?? null}
                    withStatus={false}
                  />
                </Table.Cell>
                <Table.Cell>
                  <FieldStatusBadge status={field.status} />
                </Table.Cell>
                <Table.Cell>
                  <ConfidenceCell confidence={field.confidence} calibrated={field.calibrated} />
                </Table.Cell>
                <Table.Cell className="truncate">{field.evidence ?? "—"}</Table.Cell>
                <Table.Cell className="truncate">{field.source_kind ?? "—"}</Table.Cell>
                <Table.Cell className="truncate">
                  <LocatorText locator={field.locator} />
                </Table.Cell>
                <Table.Cell className="truncate">{field.derived_by ?? "—"}</Table.Cell>
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
}: Readonly<{ records: readonly ExtractedRecord[]; fieldTypes: FieldTypes }>) {
  if (records.length === 0) {
    return <EmptyView title="No records">The page yielded no record for this schema.</EmptyView>;
  }
  return (
    <div className="flex flex-col gap-6">
      {records.map((record, index) => {
        const title = `Record ${String(index + 1)}`;
        return (
          // One answer's records keep their order, and a replayed record has no id: its title is its key.
          <section key={title} className="flex flex-col gap-2">
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
