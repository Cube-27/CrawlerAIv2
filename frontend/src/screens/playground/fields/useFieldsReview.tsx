import { useState, type ReactNode } from "react";
import type { JobSchemaRef } from "../../../api/jobs";
import type { PageKind, SchemaRef } from "../../../api/scrape";
import { DraftReview } from "./DraftReview";

interface Pending<R> {
  request: R;
  fields: string[];
  pageKind: PageKind;
}

/** A mode's run with the review of field names (SPEC-14 §4.10): `start(request, pageKind)` sends a request whose
 * schema is not field names at once; one whose schema is opens `drawer`, the draft for review, and sends the request
 * with the reviewed schema when the user runs it. `pageKind` is the page kind the names are drafted for. */
export function useFieldsReview<R extends { schema: SchemaRef | JobSchemaRef | null }>(
  send: (request: R) => void,
): { start: (request: R, pageKind: PageKind | null) => void; drawer: ReactNode } {
  const [pending, setPending] = useState<Pending<R> | null>(null);
  const start = (request: R, pageKind: PageKind | null) => {
    const { schema } = request;
    if (schema !== null && "fields" in schema && pageKind !== null)
      setPending({ request, fields: schema.fields, pageKind });
    else send(request);
  };
  const drawer =
    pending === null ? null : (
      <DraftReview
        fields={pending.fields}
        pageKind={pending.pageKind}
        onRun={(schema) => {
          setPending(null);
          send({ ...pending.request, schema });
        }}
        onClose={() => {
          setPending(null);
        }}
      />
    );
  return { start, drawer };
}
