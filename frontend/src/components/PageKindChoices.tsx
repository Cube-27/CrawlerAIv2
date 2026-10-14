import type { PageKind, ScrapeFormat } from "../api/scrape";
import { Choices } from "./Choices";
import { PAGE_KINDS } from "./requestOptions";

/** The page kinds whose records the server refuses, for a scrape and a batch scrape alike: SPEC-07 §4.4 and D-0502
 * leave listing records out (`check_records`). */
const NO_RECORDS_PAGE_KINDS: readonly PageKind[] = ["listing"];

/** `form` with `formats`; asking for records clears a page kind whose records the server refuses. */
export function withFormats<
  F extends { formats: readonly ScrapeFormat[]; pageKind: PageKind | null },
>(form: F, formats: readonly ScrapeFormat[]): F {
  const refused =
    formats.includes("records") &&
    form.pageKind !== null &&
    NO_RECORDS_PAGE_KINDS.includes(form.pageKind);
  return { ...form, formats, pageKind: refused ? null : form.pageKind };
}

/** The request's `page_kind`. SPEC-07 §4.4: it is required when the formats include records, and then a page kind
 * whose records the server refuses can't be chosen. The reason is always shown, so ticking records moves nothing. */
export function PageKindChoices({
  value,
  formats,
  name,
  onChange,
}: Readonly<{
  value: PageKind | null;
  formats: readonly ScrapeFormat[];
  name?: string;
  onChange: (pageKind: PageKind) => void;
}>) {
  const records = formats.includes("records");
  return (
    <Choices
      label="Page kind"
      {...(name === undefined ? {} : { name })}
      options={PAGE_KINDS}
      value={value}
      isRequired={records}
      disabled={records ? NO_RECORDS_PAGE_KINDS : []}
      description="Records of listing pages are not available yet."
      onChange={onChange}
    />
  );
}
