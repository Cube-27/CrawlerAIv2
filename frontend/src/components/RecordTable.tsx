import { Table } from "@heroui/react";
import { useMemo, type ReactNode } from "react";
import type { FieldTypes, FieldTypeSpec } from "../api/field";
import type { StoredRecord } from "../api/records";
import { confidenceText } from "./ConfidenceCell";
import { FieldValue } from "./FieldValue";

interface Column {
  id: string;
  name: string;
  render: (record: StoredRecord) => ReactNode;
}

const RECORD_COLUMNS: Column[] = [
  { id: "mode", name: "Mode", render: (record) => record.mode },
  { id: "version", name: "Version", render: (record) => record.version },
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

function columnsOf(fieldTypes: FieldTypes): Column[] {
  return [
    ...Object.entries(fieldTypes).map(([name, spec]) => fieldColumn(name, spec)),
    ...RECORD_COLUMNS,
  ];
}

/** Records of one schema: a column per field of the schema (`fieldTypes`, in its order), then mode, version and
 * confidence. A row opens by click or by Enter (`onOpen`). */
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
  return (
    <Table>
      <Table.ScrollContainer>
        <Table.Content
          aria-label={label}
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
                {(column) => <Table.Cell>{column.render(record)}</Table.Cell>}
              </Table.Row>
            )}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}
