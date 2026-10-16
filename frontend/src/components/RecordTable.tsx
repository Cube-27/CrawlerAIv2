import { Table, Typography } from "@heroui/react";
import { useMemo, type ReactNode } from "react";
import type { FieldTypes, FieldTypeSpec } from "../api/field";
import type { StoredRecord } from "../api/records";
import { confidenceText } from "./ConfidenceCell";
import { FieldValue } from "./FieldValue";

/** The fields whose published value differs from the version the record supersedes, or null when none, as for a
 * first version (SPEC-11 §4.4). */
export function changedFieldsText({ changed_fields: changed }: StoredRecord): string | null {
  return changed.length === 0 ? null : changed.join(", ");
}

interface Column {
  id: string;
  name: string;
  render: (record: StoredRecord) => ReactNode;
}

const RECORD_COLUMNS: Column[] = [
  { id: "mode", name: "Mode", render: (record) => record.mode },
  { id: "version", name: "Version", render: (record) => record.version },
  { id: "changed", name: "Changed", render: (record) => changedFieldsText(record) ?? "—" },
  { id: "confidence", name: "Confidence", render: (record) => confidenceText(record.confidence) },
];

// Field names are user data and may equal a member's name, so a field column's id carries a prefix.
function fieldColumn(name: string, spec: FieldTypeSpec): Column {
  return {
    id: `field:${name}`,
    name,
    render: (record) => {
      const field = record.fields[name];
      return field === undefined ? "—" : <FieldValue field={field} spec={spec} />;
    },
  };
}

/** How many field columns a records table shows (D-0978): a wide schema (25 fields) gave each column a few pixels.
 * The record inspector shows every field. */
export const SHOWN_FIELDS = 6;

/** The fields the table shows: scalar fields first, as one short value fits a cell and a list or an object does not
 * (SPEC-04 §4.1 field types), each group in the schema's order, at most `SHOWN_FIELDS`. */
export function shownFields(fieldTypes: FieldTypes): [string, FieldTypeSpec][] {
  const fields = Object.entries(fieldTypes);
  const scalar = fields.filter(([, spec]) => spec.type !== "list" && spec.type !== "object");
  const nested = fields.filter(([, spec]) => spec.type === "list" || spec.type === "object");
  return [...scalar, ...nested].slice(0, SHOWN_FIELDS);
}

function columnsOf(fieldTypes: FieldTypes): Column[] {
  return [
    ...shownFields(fieldTypes).map(([name, spec]) => fieldColumn(name, spec)),
    ...RECORD_COLUMNS,
  ];
}

/** Records of one schema: a column for each of its first fields (`shownFields`), then mode, version, the fields
 * changed from the previous version, and confidence, with a line saying how many fields are left to the inspector. A
 * row opens by click or by Enter (`onOpen`). */
export function RecordTable({
  label,
  records,
  fieldTypes,
  onOpen,
}: Readonly<{
  label: string;
  records: readonly StoredRecord[];
  fieldTypes: FieldTypes;
  onOpen: (record: StoredRecord) => void;
}>) {
  const columns = useMemo(() => columnsOf(fieldTypes), [fieldTypes]);
  const total = Object.keys(fieldTypes).length;
  return (
    <div className="flex flex-col gap-2">
      {total > SHOWN_FIELDS ? (
        <Typography.Paragraph size="sm" color="muted">
          Showing {SHOWN_FIELDS} of {total} fields. Open a record to see all of them.
        </Typography.Paragraph>
      ) : null}
      <Table>
        <Table.ScrollContainer>
          {/* Fixed column widths: a page of long values truncates rather than moving the columns. */}
          <Table.Content
            aria-label={label}
            className="table-fixed"
            onRowAction={(key) => {
              const record = records.find(({ id }) => id === key);
              if (record !== undefined) onOpen(record);
            }}
          >
            <Table.Header columns={columns}>
              {(column) => (
                <Table.Column id={column.id} isRowHeader={column === columns[0]}>
                  {column.name}
                </Table.Column>
              )}
            </Table.Header>
            <Table.Body items={records}>
              {(record) => (
                <Table.Row id={record.id} columns={columns}>
                  {(column) => (
                    <Table.Cell className="truncate">{column.render(record)}</Table.Cell>
                  )}
                </Table.Row>
              )}
            </Table.Body>
          </Table.Content>
        </Table.ScrollContainer>
      </Table>
    </div>
  );
}
