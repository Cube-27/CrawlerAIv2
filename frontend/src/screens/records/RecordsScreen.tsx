import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { parseFieldTypes } from "../../api/field";
import { problemOf } from "../../api/hooks/query";
import { useRecords } from "../../api/hooks/records";
import { useSchema } from "../../api/hooks/schemas";
import { activeFilters, type RecordFilters, type StoredRecord } from "../../api/records";
import { EmptyView } from "../../components/EmptyView";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { RecordTable } from "../../components/RecordTable";
import { TablePagination } from "../../components/TablePagination";
import { RecordFiltersForm } from "./RecordFilters";
import { RecordInspector } from "./RecordInspector";

// The filters live in the URL, so a filtered list can be reloaded, shared and returned to.
function filtersOf(params: URLSearchParams): RecordFilters {
  return {
    schema_id: params.get("schema_id") ?? "",
    job_id: params.get("job_id") ?? "",
    site: params.get("site") ?? "",
  };
}

/** One page of the filtered records with previous and next. The API pages forward by cursor (SPEC-07 §4.6), so the
 * cursors of the pages before are kept here; the first page has none. */
function RecordResults({ filters }: Readonly<{ filters: RecordFilters }>) {
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [open, setOpen] = useState<StoredRecord | null>(null);
  const cursor = cursors.at(-1) ?? null;
  const records = useRecords(filters, cursor);
  const schema = useSchema(filters.schema_id);
  const problem = problemOf(records.error ?? schema.error);
  // Stable while the schema is, so opening a record leaves the table's columns and cells as they are.
  const fieldTypes = useMemo(() => parseFieldTypes(schema.data?.fields), [schema.data]);

  if (problem !== null) return <ProblemAlert problem={problem} />;
  if (!records.isSuccess || !schema.isSuccess) return <LoadingView label="Loading records" />;

  const { items, next_cursor: next } = records.data;
  return (
    <div className="flex flex-col gap-3">
      {items.length === 0 ? (
        <EmptyView title="No records">No record matches these filters.</EmptyView>
      ) : (
        <RecordTable label="Records" records={items} fieldTypes={fieldTypes} onOpen={setOpen} />
      )}
      <TablePagination
        summary={`Page ${String(cursors.length)}`}
        onPrevious={
          cursors.length > 1
            ? () => {
                setCursors(cursors.slice(0, -1));
              }
            : null
        }
        onNext={
          next === null
            ? null
            : () => {
                setCursors([...cursors, next]);
              }
        }
      />
      {open === null ? null : (
        <RecordInspector
          key={open.id}
          record={open}
          fieldTypes={fieldTypes}
          onClose={() => {
            setOpen(null);
          }}
        />
      )}
    </div>
  );
}

/** Stored records by schema, job and site (SPEC-12 §4.3): a column per schema field, and an inspector per record. */
export function RecordsScreen() {
  const [params, setParams] = useSearchParams();
  const filters = filtersOf(params);
  const key = new URLSearchParams(activeFilters(filters)).toString();
  return (
    <section className="flex flex-col gap-6">
      <PageHeader title="Records" />
      <RecordFiltersForm
        key={key}
        filters={filters}
        onSubmit={(next) => {
          setParams(activeFilters(next));
        }}
      />
      {filters.schema_id === "" ? (
        <EmptyView title="Choose a schema">
          Records are listed by schema, with a column for each of its fields.
        </EmptyView>
      ) : (
        <RecordResults key={key} filters={filters} />
      )}
    </section>
  );
}
