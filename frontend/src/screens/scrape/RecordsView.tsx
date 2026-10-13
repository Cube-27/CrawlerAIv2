import { Table, Typography } from "@heroui/react";
import type { RecordField, ScrapeRecord } from "../../api/scrape";
import { ConfidenceCell } from "../../components/ConfidenceCell";
import { EmptyView } from "../../components/EmptyView";
import { FieldStatusBadge } from "../../components/FieldStatusBadge";
import { FieldValue } from "../../components/FieldValue";
import { LocatorText } from "../../components/LocatorText";
import { StatusLabel } from "../../components/StatusLabel";
import type { FieldTypes } from "./run";

/** One record's fields, one row each, with every `field_meta` attribute the API returns (SPEC-07 §4.4). */
function RecordFields({
  record,
  index,
  fieldTypes,
}: Readonly<{ record: ScrapeRecord; index: number; fieldTypes: FieldTypes }>) {
  const fields: (RecordField & { name: string })[] = Object.entries(record.fields).map(
    ([name, field]) => ({ ...field, name }),
  );
  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <Typography.Heading level={3}>Record {index + 1}</Typography.Heading>
        <StatusLabel
          text={record.complete ? "complete" : "incomplete"}
          tone={record.complete ? "success" : "warning"}
        />
        <Typography.Paragraph size="sm" color="muted">
          Mode {record.mode} · confidence{" "}
          {record.confidence === null ? "—" : record.confidence.toFixed(2)}
        </Typography.Paragraph>
      </div>
      <Table>
        <Table.ScrollContainer>
          <Table.Content aria-label={`Record ${String(index + 1)} fields`}>
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
    </section>
  );
}

/** The records a scrape extracted, or why there are none. */
export function RecordsView({
  records,
  fieldTypes,
}: Readonly<{ records: readonly ScrapeRecord[]; fieldTypes: FieldTypes }>) {
  if (records.length === 0) {
    return <EmptyView title="No records">The page yielded no record for this schema.</EmptyView>;
  }
  return (
    <div className="flex flex-col gap-6">
      {records.map((record, index) => (
        <RecordFields key={record.id} record={record} index={index} fieldTypes={fieldTypes} />
      ))}
    </div>
  );
}
