import type { SearchRequest } from "../../../api/jobs";
import type { SchemaPageKind } from "../../../api/schemas";
import type { PageFormat } from "../FormatSelect";
import { NO_ERRORS, optionalNumber, requestFormats, schemaPageKindErrors } from "../pageRequest";

/** Search's options panel: `limit`, and whether the results are scraped by a batch job (`scrape`), with the
 * Metadata in JSON view option. An empty limit (NaN) is left out, so the server's default applies. */
export interface SearchOptions {
  limit: number;
  scrape: boolean;
  metadataInJson: boolean;
}

export const DEFAULT_SEARCH_OPTIONS: SearchOptions = {
  limit: Number.NaN,
  scrape: false,
  metadataInJson: false,
};

export interface SearchFormState {
  query: string;
  formats: readonly PageFormat[];
  schemaId: string;
  schemaPageKind: SchemaPageKind | null;
  options: SearchOptions;
}

export const INITIAL_SEARCH: SearchFormState = {
  query: "",
  formats: ["markdown"],
  schemaId: "",
  schemaPageKind: null,
  options: DEFAULT_SEARCH_OPTIONS,
};

const NO_QUERY = { query: "Enter what to search for." };
const NO_FORMAT = {
  formats: "Choose a format, Metadata in JSON or a schema to scrape the results.",
};

/** The scrape's form, in the shape the shared format helpers read: field names are not offered here. */
function scrapeForm(form: SearchFormState) {
  return { ...form, options: { metadataInJson: form.options.metadataInJson, fields: [] } };
}

/** Why `form` can't be sent, by field. Scraping the results asks for at least one format, or a stored schema, whose
 * records are for its own page kind. */
export function searchErrors(form: SearchFormState): Readonly<Record<string, string>> {
  if (form.query.trim() === "") return NO_QUERY;
  if (!form.options.scrape) return NO_ERRORS;
  if (form.schemaId !== "") return schemaPageKindErrors(form.schemaPageKind) ?? NO_ERRORS;
  return requestFormats(scrapeForm(form)).length === 0 ? NO_FORMAT : NO_ERRORS;
}

/** The request for `form`, or null when it can't be sent (`searchErrors`). A schema's results are `records` alone
 * (a batch's results are records or page outputs). */
export function buildSearch(form: SearchFormState): SearchRequest | null {
  if (searchErrors(form) !== NO_ERRORS) return null;
  const { options } = form;
  const withSchema = form.schemaId !== "" && form.schemaPageKind !== null;
  return {
    query: form.query.trim(),
    ...optionalNumber("limit", options.limit),
    ...(options.scrape
      ? {
          scrape: withSchema
            ? {
                formats: ["records"],
                schema: { id: form.schemaId },
                page_kind: form.schemaPageKind,
              }
            : { formats: requestFormats(scrapeForm(form)) },
        }
      : {}),
  } as SearchRequest;
}
