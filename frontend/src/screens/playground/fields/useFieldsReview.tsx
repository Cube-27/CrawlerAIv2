import { useState, type ReactNode } from "react";
import type { JobSchemaRef } from "../../../api/jobs";
import type { PageKind, SchemaRef } from "../../../api/scrape";
import { DraftReview } from "./DraftReview";

/** A run request as far as its review reads it: the schema, and the page kind of a page request or the rules of a
 * crawl. */
interface Reviewed {
  schema: SchemaRef | JobSchemaRef | null;
  page_kind?: PageKind | null;
  page_kind_rules?: readonly { page_kind: PageKind }[];
}

interface Pending<R> {
  request: R;
  fields: string[];
  pageKind: PageKind;
}

/** The page kind field names are drafted for: the request's, or a crawl's rules' one page kind. */
function pageKindOf(request: Reviewed): PageKind | null {
  if (request.page_kind !== undefined) return request.page_kind;
  const kinds = new Set(request.page_kind_rules?.map((rule) => rule.page_kind));
  const [kind] = kinds;
  return kinds.size === 1 && kind !== undefined ? kind : null;
}

/** A mode's run with the review of field names: `start(request)` sends a request whose schema is not
 * field names at once; one whose schema is opens `drawer`, the draft for review, and sends the request with the
 * reviewed schema when the user runs it. The form's checks make sure field names come with a page kind. */
export function useFieldsReview<R extends Reviewed>(
  send: (request: R) => void,
): { start: (request: R) => void; drawer: ReactNode } {
  const [pending, setPending] = useState<Pending<R> | null>(null);
  const start = (request: R) => {
    const { schema } = request;
    const pageKind = pageKindOf(request);
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
